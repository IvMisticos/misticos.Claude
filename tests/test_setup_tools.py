import json
import shutil
import subprocess
import sys

import pytest
from conftest import ROOT

WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"
MARKETPLACE_ADD = "claude plugin marketplace add GoogleChrome/modern-web-guidance"
INSTALL = f"claude plugin install {WEB_GUIDANCE_PLUGIN} --scope user"
REAPPLY_SETTINGS = "run.sh setup_settings.py"
FAKE_CLAUDE = """#!/usr/bin/env bash
echo "claude $*" >> "$HOME/calls"
[ "$2" != "${CLAUDE_FAILS_AT-}" ]
"""
FAKE_RUN = """#!/usr/bin/env bash
echo "run.sh $*" >> "$HOME/calls"
"""


@pytest.fixture
def hooks(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("setup_tools.py", "json_values.py"):
        shutil.copy(ROOT / "hooks" / name, hooks / name)
    run_sh = hooks / "run.sh"
    run_sh.write_text(FAKE_RUN)
    run_sh.chmod(0o755)
    return hooks


@pytest.fixture
def set_up_tools(home, fake_bin, hooks):
    bin_dir = fake_bin("claude", FAKE_CLAUDE)

    def set_up(**extra_environment):
        result = subprocess.run(
            [sys.executable, hooks / "setup_tools.py"],
            env={
                "HOME": str(home),
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                **extra_environment,
            },
            capture_output=True,
            check=False,
            timeout=30,
        )
        calls = home / "calls"
        logged = calls.read_text().splitlines() if calls.exists() else []
        return result.returncode, logged

    return set_up


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_settings_are_reapplied_after_the_plugin_install(set_up_tools):
    assert set_up_tools() == (0, [MARKETPLACE_ADD, INSTALL, REAPPLY_SETTINGS])


def test_failed_install_still_reapplies_settings(set_up_tools):
    status, calls = set_up_tools(CLAUDE_FAILS_AT="install")
    assert status != 0
    assert calls == [MARKETPLACE_ADD, INSTALL, REAPPLY_SETTINGS]


def test_installed_plugin_is_left_alone(set_up_tools, home):
    installed = home / ".claude" / "plugins" / "installed_plugins.json"
    write_json(installed, {"plugins": {WEB_GUIDANCE_PLUGIN: []}})
    assert set_up_tools() == (0, [])


def test_plugin_the_user_disabled_is_not_installed(set_up_tools, home):
    settings = home / ".claude" / "settings.json"
    write_json(settings, {"enabledPlugins": {WEB_GUIDANCE_PLUGIN: False}})
    assert set_up_tools() == (0, [])
