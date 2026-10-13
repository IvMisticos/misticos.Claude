import hashlib
import shutil
import subprocess

import pytest
from conftest import ROOT

HOOKS = ROOT / "hooks"
FAKE_UV = """#!/usr/bin/env bash
echo "uv $*"
exit "${UV_STATUS-0}"
"""


@pytest.fixture
def plugin_data(tmp_path):
    return tmp_path / "plugin-data"


@pytest.fixture
def marker(plugin_data):
    return plugin_data / "setup-complete"


@pytest.fixture
def boot_id_file(tmp_path):
    path = tmp_path / "boot_id"
    path.write_text("boot-one\n")
    return path


@pytest.fixture
def current_key(boot_id_file):
    digest = hashlib.sha256((HOOKS / "setup.py").read_bytes()).hexdigest()
    return f"{digest} boot-one\n"


@pytest.fixture
def run_hook(tmp_path, home, fake_bin, plugin_data, boot_id_file):
    bin_dir = fake_bin("uv", FAKE_UV)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(HOOKS / "run.sh", scripts / "run.sh")
    shutil.copy(HOOKS / "setup.py", scripts / "setup.py")
    (scripts / "other.py").touch()

    def run(script="setup.py", path=f"{bin_dir}:/usr/bin:/bin", **extra_environment):
        environment = {
            "HOME": str(home),
            "PATH": path,
            "SETUP_BOOT_ID_FILE": str(boot_id_file),
            "CLAUDE_PLUGIN_DATA": str(plugin_data),
            **extra_environment,
        }
        return subprocess.run(
            [scripts / "run.sh", script],
            env={name: value for name, value in environment.items() if value},
            capture_output=True,
            text=True,
            check=False,
        )

    return run


def ran_uv(result):
    return result.stdout.startswith("uv run ")


def write_marker(plugin_data, marker, content):
    plugin_data.mkdir()
    marker.write_text(content)


def test_matching_marker_skips_setup(run_hook, plugin_data, marker, current_key):
    write_marker(plugin_data, marker, current_key)
    result = run_hook()
    assert (result.returncode, result.stdout) == (0, "")


def test_missing_marker_runs_setup_and_writes_it(run_hook, marker, current_key):
    assert ran_uv(run_hook())
    assert marker.read_text() == current_key


def test_stale_marker_runs_setup_and_rewrites_it(
    run_hook, plugin_data, marker, current_key
):
    write_marker(plugin_data, marker, "stale\n")
    assert ran_uv(run_hook())
    assert marker.read_text() == current_key


def test_failed_setup_writes_no_marker(run_hook, marker):
    result = run_hook(UV_STATUS="3")
    assert (ran_uv(result), result.returncode) == (True, 3)
    assert not marker.exists()


def test_failed_setup_keeps_a_stale_marker_stale(run_hook, plugin_data, marker):
    write_marker(plugin_data, marker, "stale\n")
    run_hook(UV_STATUS="3")
    assert marker.read_text() == "stale\n"


def test_other_scripts_never_skip(run_hook, plugin_data, marker, current_key):
    write_marker(plugin_data, marker, current_key)
    assert ran_uv(run_hook("other.py"))


def test_other_scripts_write_no_marker(run_hook, marker):
    run_hook("other.py")
    assert not marker.exists()


def test_unset_plugin_data_always_runs_setup(run_hook, tmp_path):
    assert ran_uv(run_hook(CLAUDE_PLUGIN_DATA=""))
    assert not (tmp_path / "setup-complete").exists()


def test_new_boot_runs_setup_again(
    run_hook, plugin_data, marker, boot_id_file, current_key
):
    write_marker(plugin_data, marker, current_key)
    boot_id_file.write_text("boot-two\n")
    assert ran_uv(run_hook())
    assert marker.read_text().endswith(" boot-two\n")


def test_unreadable_boot_id_still_skips_when_marker_matches(
    run_hook, plugin_data, marker, boot_id_file
):
    boot_id_file.unlink()
    assert ran_uv(run_hook())
    assert not run_hook().stdout
    assert marker.read_text().endswith(" \n")


def test_missing_hash_tool_runs_setup_without_a_marker(
    run_hook, tmp_path, fake_bin, marker
):
    tools = fake_bin("uv", FAKE_UV).parent / "no-hash-tools"
    tools.mkdir()
    (tools / "uv").symlink_to(tmp_path / "bin" / "uv")
    for tool in ("bash", "cat", "cut", "dirname", "mkdir"):
        (tools / tool).symlink_to(shutil.which(tool))
    result = run_hook(path=str(tools))
    assert (ran_uv(result), result.returncode) == (True, 0)
    assert not marker.exists()
