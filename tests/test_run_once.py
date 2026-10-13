import shutil
import subprocess
import time

import pytest
from conftest import ROOT

FAKE_UV = """#!/usr/bin/env bash
echo "uv $*"
echo "${*##*/}" >> "$HOME/uv-calls"
exit "${UV_STATUS-0}"
"""
SCRIPTS = {
    "settings.py": "import os\nfrom shared import helper\n",
    "tools.py": "from shared import helper\n",
    "listed.py": "import os, deep.inner as inner, shared\n",
    "shared.py": "import json\nfrom deep import value\n",
    "deep.py": "value = 1\n",
    "unrelated.py": "value = 2\n",
}


@pytest.fixture
def plugin_data(tmp_path):
    return tmp_path / "plugin-data"


@pytest.fixture
def scripts(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(ROOT / "hooks" / "run.sh", scripts / "run.sh")
    for name, source in SCRIPTS.items():
        (scripts / name).write_text(source)
    return scripts


@pytest.fixture
def hooks_copy(tmp_path):
    hooks = tmp_path / "hooks"
    shutil.copytree(ROOT / "hooks", hooks)
    return hooks


def hook_command(scripts, script, *, once=True, after=None):
    once_flag = ["--once"] if once else []
    after_flag = ["--after", after] if after else []
    return [scripts / "run.sh", *once_flag, *after_flag, script]


def hook_environment(home, path, plugin_data, extra_environment):
    environment = {
        "HOME": str(home),
        "PATH": path,
        "CLAUDE_PLUGIN_DATA": str(plugin_data),
        **extra_environment,
    }
    return {name: value for name, value in environment.items() if value}


def runner(scripts, home, bin_dir, plugin_data):
    def run(
        script="settings.py",
        *,
        once=True,
        after=None,
        path=f"{bin_dir}:/usr/bin:/bin",
        **extra_environment,
    ):
        return subprocess.run(
            hook_command(scripts, script, once=once, after=after),
            env=hook_environment(home, path, plugin_data, extra_environment),
            capture_output=True,
            text=True,
            check=False,
        )

    return run


@pytest.fixture
def uv_bin(fake_bin):
    return fake_bin("uv", FAKE_UV)


@pytest.fixture
def run_hook(home, uv_bin, plugin_data, scripts):
    return runner(scripts, home, uv_bin, plugin_data)


@pytest.fixture
def run_real_hook(home, uv_bin, plugin_data, hooks_copy):
    return runner(hooks_copy, home, uv_bin, plugin_data)


@pytest.fixture
def start_tools_after_settings(home, uv_bin, plugin_data, scripts):
    def start():
        return subprocess.Popen(
            hook_command(scripts, "tools.py", after="settings.py"),
            env=hook_environment(home, f"{uv_bin}:/usr/bin:/bin", plugin_data, {}),
            stdout=subprocess.DEVNULL,
        )

    return start


def fake_sleep(fake_bin, *, sleeps):
    real_sleep = f'exec {shutil.which("sleep")} "$@"' if sleeps else ""
    fake_bin("sleep", f'#!/usr/bin/env bash\ntouch "$HOME/waited"\n{real_sleep}\n')


def wait_for(path):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


def uv_calls(home):
    calls = home / "uv-calls"
    return calls.read_text().splitlines() if calls.exists() else []


def ran_uv(result):
    return result.stdout.startswith("uv run ")


def marker_of(plugin_data, script):
    return plugin_data / f"{script.removesuffix('.py')}-complete"


def write_stale_marker(plugin_data, script):
    marker = marker_of(plugin_data, script)
    plugin_data.mkdir()
    marker.write_text("stale\n")
    return marker


def edit(scripts, name):
    with (scripts / name).open("a") as script:
        script.write("edited = True\n")


def test_first_run_runs_the_script_and_writes_its_marker(run_hook, plugin_data):
    result = run_hook()
    assert result.stdout.endswith("/settings.py\n")
    assert marker_of(plugin_data, "settings.py").read_text().strip()


def test_completed_script_is_skipped(run_hook):
    run_hook()
    result = run_hook()
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.parametrize("edited", ["settings.py", "shared.py", "deep.py"])
def test_editing_the_script_or_a_local_import_reruns_it(run_hook, scripts, edited):
    run_hook()
    edit(scripts, edited)
    assert ran_uv(run_hook())
    assert not ran_uv(run_hook())


@pytest.mark.parametrize("edited", ["deep.py", "shared.py"])
def test_every_module_in_an_import_list_counts(run_hook, scripts, edited):
    run_hook("listed.py")
    edit(scripts, edited)
    assert ran_uv(run_hook("listed.py"))


def test_real_setup_markers_cover_shared_modules(run_real_hook, hooks_copy):
    setup_scripts = ("setup_settings.py", "setup_tools.py")
    for script in setup_scripts:
        run_real_hook(script)
    edit(hooks_copy, "json_values.py")
    assert [ran_uv(run_real_hook(script)) for script in setup_scripts] == [True, True]


def test_editing_another_script_keeps_the_marker(run_hook, scripts):
    run_hook()
    edit(scripts, "unrelated.py")
    assert not ran_uv(run_hook())


def test_editing_one_script_keeps_the_other_marker(run_hook, scripts):
    run_hook("settings.py")
    run_hook("tools.py")
    edit(scripts, "tools.py")
    assert not ran_uv(run_hook("settings.py"))
    assert ran_uv(run_hook("tools.py"))


def test_editing_shared_code_reruns_every_script_that_imports_it(run_hook, scripts):
    run_hook("settings.py")
    run_hook("tools.py")
    edit(scripts, "shared.py")
    assert ran_uv(run_hook("settings.py"))
    assert ran_uv(run_hook("tools.py"))


def test_stale_marker_is_rewritten(run_hook, plugin_data):
    marker = write_stale_marker(plugin_data, "settings.py")
    assert ran_uv(run_hook())
    assert marker.read_text() != "stale\n"


def test_failed_run_writes_no_marker(run_hook, plugin_data):
    result = run_hook(UV_STATUS="3")
    assert (ran_uv(result), result.returncode) == (True, 3)
    assert not marker_of(plugin_data, "settings.py").exists()


def test_failed_run_keeps_a_stale_marker_stale(run_hook, plugin_data):
    marker = write_stale_marker(plugin_data, "settings.py")
    run_hook(UV_STATUS="3")
    assert marker.read_text() == "stale\n"


def test_without_once_the_script_always_runs(run_hook):
    run_hook()
    assert ran_uv(run_hook(once=False))


def test_without_once_no_marker_is_written(run_hook, plugin_data):
    run_hook(once=False)
    assert not plugin_data.exists()


def test_unset_plugin_data_always_runs(run_hook):
    assert ran_uv(run_hook(CLAUDE_PLUGIN_DATA=""))
    assert ran_uv(run_hook(CLAUDE_PLUGIN_DATA=""))


def test_missing_hash_tool_runs_without_a_marker(
    run_hook, tmp_path, fake_bin, plugin_data
):
    tools = fake_bin("uv", FAKE_UV).parent / "no-hash-tools"
    tools.mkdir()
    (tools / "uv").symlink_to(tmp_path / "bin" / "uv")
    for tool in ("bash", "cat", "cut", "dirname", "mkdir"):
        (tools / tool).symlink_to(shutil.which(tool))
    result = run_hook(path=str(tools))
    assert (ran_uv(result), result.returncode) == (True, 0)
    assert not marker_of(plugin_data, "settings.py").exists()


def test_after_waits_until_the_other_script_completes(
    run_hook, start_tools_after_settings, fake_bin, home
):
    fake_sleep(fake_bin, sleeps=True)
    tools = start_tools_after_settings()
    wait_for(home / "waited")
    assert uv_calls(home) == []
    run_hook("settings.py")
    assert tools.wait(timeout=10) == 0
    assert uv_calls(home) == ["run settings.py", "run tools.py"]


def test_after_runs_at_once_when_the_other_script_already_completed(
    run_hook, fake_bin, home
):
    fake_sleep(fake_bin, sleeps=True)
    run_hook("settings.py")
    assert ran_uv(run_hook("tools.py", after="settings.py"))
    assert not (home / "waited").exists()


def test_after_stops_waiting_eventually(run_hook, fake_bin, home):
    fake_sleep(fake_bin, sleeps=False)
    assert ran_uv(run_hook("tools.py", after="settings.py"))
    assert (home / "waited").exists()


def test_after_does_not_wait_without_plugin_data(run_hook, fake_bin, home):
    fake_sleep(fake_bin, sleeps=True)
    assert ran_uv(run_hook("tools.py", after="settings.py", CLAUDE_PLUGIN_DATA=""))
    assert not (home / "waited").exists()
