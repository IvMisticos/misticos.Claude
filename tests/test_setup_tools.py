import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

import pytest
from conftest import ROOT, FakeBin
from json_values import JsonValue

WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"
INSTALL = (
    "claude plugin install modern-web-guidance"
    " --marketplace GoogleChrome/modern-web-guidance --scope user"
)
REAPPLY_SETTINGS = "run.sh setup_settings.py"
ENABLE = f"claude plugin enable {WEB_GUIDANCE_PLUGIN} --scope user"
ENABLE_IN_SETTINGS = """
import json, sys
from pathlib import Path
settings_path, plugin, action = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
enabled = settings.setdefault("enabledPlugins", {})
if action == "enable" and enabled.get(plugin) is True:
    sys.exit("already_in_goal_state")
enabled[plugin] = True
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(settings))
"""
FAKE_CLAUDE = f"""#!/usr/bin/env bash
echo "claude $*" >> "$HOME/calls"
[ "$2" != "${{CLAUDE_FAILS_AT-}}" ] || exit 1
case "$2" in
  install)
    exec python3 -c '{ENABLE_IN_SETTINGS}' "$HOME/.claude/settings.json" "$3@googlechrome" "$2" ;;
  enable)
    exec python3 -c '{ENABLE_IN_SETTINGS}' "$HOME/.claude/settings.json" "$3" "$2" ;;
esac
"""
FAKE_RUN = """#!/usr/bin/env bash
echo "run.sh $*" >> "$HOME/calls"
[ -z "${STALE_SETTINGS-}" ] || echo '{}' > "$HOME/.claude/settings.json"
"""
FAKE_DOWNLOAD = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$HOME/calls"
"""
FAKE_MISE = """#!/usr/bin/env bash
echo "mise $* in $(basename "$PWD")" >> "$HOME/calls"
[ "$1 $(basename "$PWD")" != "${MISE_FAILS_AT-}" ] || exit 1
"""


class SetUpTools(Protocol):
    def __call__(self, **extra_environment: str) -> tuple[int, list[str]]: ...


@pytest.fixture
def hooks(tmp_path: Path) -> Path:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("setup_tools.py", "json_values.py"):
        shutil.copy(ROOT / "hooks" / name, hooks / name)
    run_sh = hooks / "run.sh"
    run_sh.write_text(FAKE_RUN)
    run_sh.chmod(0o755)
    return hooks


@pytest.fixture
def set_up_tools(home: Path, fake_bin: FakeBin, hooks: Path) -> SetUpTools:
    bin_dir = fake_bin("claude", FAKE_CLAUDE)
    fake_bin("curl", FAKE_DOWNLOAD)
    fake_bin("apt-get", FAKE_DOWNLOAD)
    fake_bin("mise", FAKE_MISE)

    def set_up(**extra_environment: str) -> tuple[int, list[str]]:
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


def write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_settings_are_reapplied_after_the_plugin_install(
    set_up_tools: SetUpTools,
) -> None:
    assert set_up_tools() == (0, [INSTALL, REAPPLY_SETTINGS])


def test_plugin_is_enabled_when_reapplied_settings_lost_it(
    set_up_tools: SetUpTools,
) -> None:
    assert set_up_tools(STALE_SETTINGS="1") == (
        0,
        [INSTALL, REAPPLY_SETTINGS, ENABLE],
    )


def test_failed_install_still_reapplies_settings(set_up_tools: SetUpTools) -> None:
    status, calls = set_up_tools(CLAUDE_FAILS_AT="install")
    assert status != 0
    assert calls == [INSTALL, REAPPLY_SETTINGS]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_tools_install_after_a_plugin_failure(set_up_tools: SetUpTools) -> None:
    status, calls = set_up_tools(CLAUDE_FAILS_AT="install", CCR_AGENT_PROXY_ENABLED="1")
    assert status != 0
    assert calls[:2] == [INSTALL, REAPPLY_SETTINGS]
    assert any(call.startswith("curl ") for call in calls[2:])


def test_installed_plugin_is_left_alone(set_up_tools: SetUpTools, home: Path) -> None:
    installed = home / ".claude" / "plugins" / "installed_plugins.json"
    write_json(installed, {"plugins": {WEB_GUIDANCE_PLUGIN: []}})
    assert set_up_tools() == (0, [])


def test_plugin_the_user_disabled_is_not_installed(
    set_up_tools: SetUpTools, home: Path
) -> None:
    settings = home / ".claude" / "settings.json"
    write_json(settings, {"enabledPlugins": {WEB_GUIDANCE_PLUGIN: False}})
    assert set_up_tools() == (0, [])


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_installs_mise_tools_of_each_repo(
    set_up_tools: SetUpTools, tmp_path: Path
) -> None:
    projects = tmp_path / "projects"
    (projects / "with-mise").mkdir(parents=True)
    (projects / "with-mise" / "mise.toml").write_text("[tools]\n")
    (projects / "with-tool-versions").mkdir()
    (projects / "with-tool-versions" / ".tool-versions").write_text("")
    (projects / "without-mise").mkdir()
    _, calls = set_up_tools(
        CCR_AGENT_PROXY_ENABLED="1", CLAUDE_PROJECT_DIR=str(projects)
    )
    assert [call for call in calls if call.startswith("mise ")] == [
        "mise trust --all --quiet in with-mise",
        "mise install in with-mise",
        "mise trust --all --quiet in with-tool-versions",
        "mise install in with-tool-versions",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_failed_mise_install_is_retried_once(
    set_up_tools: SetUpTools, tmp_path: Path
) -> None:
    repo = tmp_path / "projects" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    status, calls = set_up_tools(
        CCR_AGENT_PROXY_ENABLED="1",
        CLAUDE_PROJECT_DIR=str(repo.parent),
        MISE_FAILS_AT="install repo",
    )
    assert status != 0
    assert [call for call in calls if call.startswith("mise ")] == [
        "mise trust --all --quiet in repo",
        "mise install in repo",
        "mise install in repo",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_failed_repo_does_not_stop_the_next_one(
    set_up_tools: SetUpTools, tmp_path: Path
) -> None:
    projects = tmp_path / "projects"
    for name in ("broken", "working"):
        (projects / name).mkdir(parents=True)
        (projects / name / "mise.toml").write_text("[tools]\n")
    status, calls = set_up_tools(
        CCR_AGENT_PROXY_ENABLED="1",
        CLAUDE_PROJECT_DIR=str(projects),
        MISE_FAILS_AT="trust broken",
    )
    assert status != 0
    assert [call for call in calls if call.startswith("mise ")] == [
        "mise trust --all --quiet in broken",
        "mise trust --all --quiet in working",
        "mise install in working",
    ]
