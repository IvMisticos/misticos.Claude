import importlib.util
import shutil
import subprocess
import sys
import types

import pytest
from conftest import ROOT

HOOKS = ROOT / "hooks"
MARKER_NAME = ".setup-complete"
STEPS = (
    "install_web_guidance_plugin",
    "configure_claude_settings",
    "configure_codex",
    "install_cloud_tools",
)


@pytest.fixture
def setup_module(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tomli_w", types.ModuleType("tomli_w"))
    monkeypatch.syspath_prepend(str(HOOKS))
    spec = importlib.util.spec_from_file_location("setup_hook", HOOKS / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SETUP_MARKER == ROOT / MARKER_NAME
    monkeypatch.setattr(module, "SETUP_MARKER", tmp_path / MARKER_NAME)
    return module


@pytest.fixture
def steps_run(monkeypatch, setup_module):
    calls = []
    for step in STEPS:
        monkeypatch.setattr(setup_module, step, lambda step=step: calls.append(step))
    return calls


def test_marker_is_ignored_by_git():
    assert MARKER_NAME in (ROOT / ".gitignore").read_text().splitlines()


def test_does_nothing_when_the_marker_exists(setup_module, steps_run):
    setup_module.SETUP_MARKER.touch()
    setup_module.main()
    assert steps_run == []


def test_a_successful_run_writes_the_marker(setup_module, steps_run):
    setup_module.main()
    assert steps_run == list(STEPS)
    assert setup_module.SETUP_MARKER.exists()


def test_a_failed_run_leaves_no_marker(monkeypatch, setup_module, steps_run):
    def fail():
        raise subprocess.CalledProcessError(1, "apt-get")

    monkeypatch.setattr(setup_module, "install_cloud_tools", fail)
    with pytest.raises(subprocess.CalledProcessError):
        setup_module.main()
    assert not setup_module.SETUP_MARKER.exists()


def test_run_script_skips_setup_when_the_marker_exists(tmp_path):
    hooks = tmp_path / "plugin" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOKS / "run.sh", hooks / "run.sh")
    (hooks / "setup.py").touch()
    (hooks.parent / MARKER_NAME).touch()
    result = subprocess.run(
        [hooks / "run.sh", "setup.py"],
        env={"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert (result.stdout, result.stderr) == ("", "")
    assert not (tmp_path / "home").exists()
