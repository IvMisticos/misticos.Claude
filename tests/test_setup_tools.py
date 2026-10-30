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
echo "mise $* in $(basename "$PWD")${MISE_GLOBAL_CONFIG_FILE:+ alone}" >> "$HOME/calls"
[ "$1 $(basename "$PWD")" != "${MISE_FAILS_AT-}" ] || exit 1
installs="$HOME/mise-installs"
case "$1 ${2-}" in
  "config get") grep -qx "$4" "$HOME/global-mise-tools" 2>/dev/null ;;
  "which "*) [ -e "$installs/$2" ] && echo "$installs/$2" ;;
  "install "*)
    mkdir -p "$installs"
    for tool in "${@:2}"; do touch "$installs/$tool"; done
    ;;
esac
"""
REGISTER_PLUGIN_TOOLS = [
    f"mise config set --global tools.{name} {version} in home"
    for name, version in (
        ("uv", "latest"),
        ("gh", "latest"),
        ("jq", "latest"),
        ("git-lfs", "latest"),
        ("bun", "latest"),
        ("dotnet", "lts"),
    )
]
INSTALL_UP_FRONT = "mise install uv gh jq git-lfs in home"


class SetUpTools(Protocol):
    def __call__(self, **extra_environment: str) -> tuple[int, list[str]]: ...


@pytest.fixture
def hooks(tmp_path: Path) -> Path:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("setup_tools.py", "json_values.py", "install_lock.py"):
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
    fake_bin("git", FAKE_DOWNLOAD)

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
            cwd=home,
        )
        calls = home / "calls"
        logged = calls.read_text().splitlines() if calls.exists() else []
        return result.returncode, logged

    return set_up


def mise_calls_in_projects(calls: list[str]) -> list[str]:
    return [
        call
        for call in calls
        if call.startswith("mise ") and not call.endswith(" in home")
    ]


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
    assert INSTALL_UP_FRONT in calls[2:]


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
    assert mise_calls_in_projects(calls) == [
        "mise trust --all --quiet in with-mise",
        "mise install in with-mise alone",
        "mise trust --all --quiet in with-tool-versions",
        "mise install in with-tool-versions alone",
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
    assert mise_calls_in_projects(calls) == [
        "mise trust --all --quiet in repo",
        "mise install in repo alone",
        "mise install in repo alone",
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
    assert mise_calls_in_projects(calls) == [
        "mise trust --all --quiet in broken",
        "mise trust --all --quiet in working",
        "mise install in working alone",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_adds_plugin_tools_to_the_global_mise_config(
    set_up_tools: SetUpTools, home: Path
) -> None:
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    registered = [call for call in calls if call.startswith("mise config set ")]
    assert registered == REGISTER_PLUGIN_TOOLS
    assert INSTALL_UP_FRONT in calls
    assert (home / ".config" / "mise" / "config.toml").is_file()


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_keeps_global_mise_tools_the_user_chose(
    set_up_tools: SetUpTools, home: Path
) -> None:
    (home / "global-mise-tools").write_text("tools.dotnet\ntools.uv\n")
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    registered = [call for call in calls if call.startswith("mise config set ")]
    assert registered == [
        call
        for call in REGISTER_PLUGIN_TOOLS
        if " tools.dotnet " not in call and " tools.uv " not in call
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
@pytest.mark.parametrize(
    ("project_file", "tool"),
    [("App.csproj", "dotnet"), ("global.json", "dotnet"), ("package.json", "bun")],
)
def test_cloud_session_installs_tools_a_project_uses(
    set_up_tools: SetUpTools, tmp_path: Path, project_file: str, tool: str
) -> None:
    repo = tmp_path / "projects" / "repo"
    repo.mkdir(parents=True)
    (repo / project_file).write_text("")
    _, calls = set_up_tools(
        CCR_AGENT_PROXY_ENABLED="1", CLAUDE_PROJECT_DIR=str(repo.parent)
    )
    assert f"mise install uv gh jq git-lfs {tool} in home" in calls


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_keeps_a_working_dotnet_link_until_mise_has_dotnet(
    set_up_tools: SetUpTools, home: Path
) -> None:
    own_dotnet = home / ".dotnet" / "dotnet"
    own_dotnet.parent.mkdir()
    own_dotnet.write_text("")
    dotnet_link = home / ".local" / "bin" / "dotnet"
    dotnet_link.parent.mkdir(parents=True)
    dotnet_link.symlink_to(own_dotnet)
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert dotnet_link.readlink() == own_dotnet


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_links_dotnet_once_mise_has_it(
    set_up_tools: SetUpTools, home: Path
) -> None:
    mise_dotnet = home / "mise-installs" / "dotnet"
    mise_dotnet.parent.mkdir()
    mise_dotnet.write_text("")
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert (home / ".local" / "bin" / "dotnet").readlink() == mise_dotnet


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_links_plugin_tools_into_the_local_bin(
    set_up_tools: SetUpTools, home: Path
) -> None:
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "uv").write_text("own uv")
    (local_bin / "gh").symlink_to(home / "stale-gh")
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert (local_bin / "uv").read_text() == "own uv"
    assert (local_bin / "gh").readlink() == home / "mise-installs" / "gh"
    assert (local_bin / "git-lfs").readlink() == home / "mise-installs" / "git-lfs"


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_sets_up_git_lfs(set_up_tools: SetUpTools) -> None:
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert "git lfs install --skip-repo" in calls


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_waits_for_another_tool_install(
    set_up_tools: SetUpTools, home: Path
) -> None:
    holder = subprocess.run(
        ["bash", "-c", "sleep 1 >/dev/null & echo $!"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    lock = home / ".local" / "tool-install.pid"
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{holder}\n")
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert INSTALL_UP_FRONT in calls
    with pytest.raises(ProcessLookupError):
        os.kill(int(holder), 0)
    assert not lock.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
@pytest.mark.parametrize("content", ["", "not a pid\n"])
def test_cloud_session_takes_over_a_garbled_install_lock(
    set_up_tools: SetUpTools, home: Path, content: str
) -> None:
    lock = home / ".local" / "tool-install.pid"
    lock.parent.mkdir(parents=True)
    lock.write_text(content)
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert INSTALL_UP_FRONT in calls
    assert not lock.exists()
