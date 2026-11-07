import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

import pytest
from conftest import ROOT, FakeBin, hook_commands, plugin_hook_command
from json_values import JsonObject

HOOKS = ROOT / "hooks"
FAKE_DOWNLOAD = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$HOME/calls"
"""
FAKE_MISE = """#!/usr/bin/env bash
echo "mise $* in $(basename "$PWD")${MISE_IGNORED_CONFIG_PATHS:+ alone}" >> "$HOME/calls"
[ "${MISE_PREFER_OFFLINE-}" = 1 ] || echo "mise $*" >> "$HOME/online-mise-calls"
[ "$1 $(basename "$PWD")" != "${MISE_FAILS_AT-}" ] || exit 1
[ -z "${MISE_TOOL_FAILS-}" ] || [ "$1 ${2-}" != "install $MISE_TOOL_FAILS" ] || exit 1
[ -z "${MISE_IGNORED_CONFIG_PATHS-}" ] || echo "$MISE_IGNORED_CONFIG_PATHS" > "$HOME/ignored"
installs="$HOME/mise-installs"
case "$1 ${2-}" in
  "config get") grep -qx "$4" "$HOME/global-mise-tools" 2>/dev/null ;;
  "which "*) [ -e "$installs/$2" ] && echo "$installs/$2" ;;
  "install "*)
    mkdir -p "$installs"
    for tool in "${@:2}"; do touch "$installs/$tool"; done
    ;;
  "use "*)
    mkdir -p "$installs"
    touch "$installs/${3%@*}"
    ;;
esac
"""
UP_FRONT_TOOLS = ("uv", "gh", "jq", "git-lfs")
REGISTER_PLUGIN_TOOLS = [
    *(f"mise use --global {name}@latest in home" for name in UP_FRONT_TOOLS),
    "mise config set --global tools.bun latest in home",
    "mise config set --global tools.dotnet lts in home",
]


class RunToolHook(Protocol):
    def __call__(
        self, script: str, payload: JsonObject, **extra_environment: str
    ) -> tuple[int, list[str]]: ...


class SetUpTools(Protocol):
    def __call__(self, **extra_environment: str) -> tuple[int, list[str]]: ...


class AddDirectory(Protocol):
    def __call__(
        self, directory: Path, **extra_environment: str
    ) -> tuple[int, list[str]]: ...


@pytest.fixture
def run_tool_hook(home: Path, fake_bin: FakeBin) -> RunToolHook:
    bin_dir = fake_bin("curl", FAKE_DOWNLOAD)
    fake_bin("apt-get", FAKE_DOWNLOAD)
    fake_bin("mise", FAKE_MISE)
    fake_bin("git", FAKE_DOWNLOAD)

    def run(
        script: str, payload: JsonObject, **extra_environment: str
    ) -> tuple[int, list[str]]:
        result = subprocess.run(
            [sys.executable, HOOKS / script],
            input=json.dumps(payload).encode(),
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

    return run


@pytest.fixture
def set_up_tools(run_tool_hook: RunToolHook) -> SetUpTools:
    def set_up(**extra_environment: str) -> tuple[int, list[str]]:
        return run_tool_hook("setup_tools.py", {}, **extra_environment)

    return set_up


@pytest.fixture
def add_directory(run_tool_hook: RunToolHook) -> AddDirectory:
    def add(directory: Path, **extra_environment: str) -> tuple[int, list[str]]:
        payload: JsonObject = {
            "hook_event_name": "DirectoryAdded",
            "directory": str(directory),
            "source": "register_repo_root",
        }
        return run_tool_hook("added_directory_tools.py", payload, **extra_environment)

    return add


def installed_tools(home: Path) -> set[str]:
    return {tool.name for tool in (home / "mise-installs").iterdir()}


def register_every_plugin_tool(home: Path) -> None:
    (home / "global-mise-tools").write_text(
        "".join(f"tools.{name}\n" for name in (*UP_FRONT_TOOLS, "bun", "dotnet"))
    )


def mise_calls_in_projects(calls: list[str]) -> list[str]:
    return [
        call
        for call in calls
        if call.startswith("mise ") and not call.endswith(" in home")
    ]


def test_tools_hook_runs_every_session() -> None:
    assert hook_commands("claude.json", "setup_tools.py")["SessionStart"] == [
        plugin_hook_command("setup_tools.py")
    ]


def test_tools_hook_outside_the_cloud_does_nothing(set_up_tools: SetUpTools) -> None:
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
    registered = [call for call in calls if call in REGISTER_PLUGIN_TOOLS]
    assert registered == REGISTER_PLUGIN_TOOLS
    assert set(UP_FRONT_TOOLS) <= installed_tools(home)


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_keeps_global_mise_tools_the_user_chose(
    set_up_tools: SetUpTools, home: Path
) -> None:
    (home / "global-mise-tools").write_text("tools.dotnet\ntools.uv\n")
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    registered = [call for call in calls if call in REGISTER_PLUGIN_TOOLS]
    assert registered == [
        call
        for call in REGISTER_PLUGIN_TOOLS
        if "tools.dotnet " not in call and " uv@" not in call
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
    assert f"mise install {tool} in home" in calls


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
    own_jq = home / "own-jq"
    own_jq.write_text("")
    (local_bin / "jq").symlink_to(own_jq)
    old_mise_gh = home / ".local" / "share" / "mise" / "installs" / "gh" / "gh"
    old_mise_gh.parent.mkdir(parents=True)
    old_mise_gh.write_text("")
    (local_bin / "gh").symlink_to(old_mise_gh)
    (local_bin / "git-lfs").symlink_to(home / "stale-git-lfs")
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert (local_bin / "uv").read_text() == "own uv"
    assert (local_bin / "jq").readlink() == own_jq
    assert (local_bin / "gh").readlink() == home / "mise-installs" / "gh"
    assert (local_bin / "git-lfs").readlink() == home / "mise-installs" / "git-lfs"


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_sets_up_git_lfs(set_up_tools: SetUpTools) -> None:
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert "git lfs install --skip-repo" in calls


def hold_install_lock_for_a_second(home: Path) -> int:
    holder = subprocess.run(
        ["bash", "-c", "sleep 1 >/dev/null & echo $!"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    lock = home / ".local" / "tool-install.pid"
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{holder}\n")
    return int(holder)


def assert_waited_for(holder: int, home: Path) -> None:
    with pytest.raises(ProcessLookupError):
        os.kill(holder, 0)
    assert not (home / ".local" / "tool-install.pid").exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_waits_for_another_tool_install(
    set_up_tools: SetUpTools, home: Path
) -> None:
    holder = hold_install_lock_for_a_second(home)
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert set(UP_FRONT_TOOLS) <= installed_tools(home)
    assert_waited_for(holder, home)


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
@pytest.mark.parametrize("content", ["", "not a pid\n"])
def test_cloud_session_takes_over_an_old_garbled_install_lock(
    set_up_tools: SetUpTools, home: Path, content: str
) -> None:
    lock = home / ".local" / "tool-install.pid"
    lock.parent.mkdir(parents=True)
    lock.write_text(content)
    an_hour_ago = time.time() - 3600
    os.utime(lock, (an_hour_ago, an_hour_ago))
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert set(UP_FRONT_TOOLS) <= installed_tools(home)
    assert not lock.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_keeps_going_after_a_plugin_tool_fails(
    set_up_tools: SetUpTools, home: Path, tmp_path: Path
) -> None:
    register_every_plugin_tool(home)
    repo = tmp_path / "projects" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    status, calls = set_up_tools(
        CCR_AGENT_PROXY_ENABLED="1",
        CLAUDE_PROJECT_DIR=str(repo.parent),
        MISE_TOOL_FAILS="gh",
    )
    assert status != 0
    assert calls.count("mise install gh in home") == 2
    assert "mise install jq in home" in calls
    assert "git lfs install --skip-repo" in calls
    assert "mise install in repo alone" in calls
    assert (home / ".local" / "bin" / "jq").is_symlink()


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_repo_installs_ignore_the_global_mise_config(
    set_up_tools: SetUpTools, home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "projects" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1", CLAUDE_PROJECT_DIR=str(repo.parent))
    global_config = home / ".config" / "mise" / "config.toml"
    assert (home / "ignored").read_text() == f"{global_config}\n"


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_every_session_installs_the_mise_tools_of_each_repo(
    set_up_tools: SetUpTools, tmp_path: Path
) -> None:
    repo = tmp_path / "projects" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1", CLAUDE_PROJECT_DIR=str(repo.parent))
    _, calls = set_up_tools(
        CCR_AGENT_PROXY_ENABLED="1", CLAUDE_PROJECT_DIR=str(repo.parent)
    )
    assert calls.count("mise install in repo alone") == 2


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_keeps_an_installed_mise(set_up_tools: SetUpTools) -> None:
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    assert not any(call.startswith("curl ") for call in calls)


def test_directory_added_hook_runs_on_every_add() -> None:
    commands = hook_commands("claude.json", "added_directory_tools.py")
    assert commands["DirectoryAdded"] == [
        plugin_hook_command("added_directory_tools.py")
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_added_repo_gets_only_its_own_mise_tools(
    add_directory: AddDirectory, tmp_path: Path
) -> None:
    repo = tmp_path / "added" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    assert add_directory(repo, CCR_AGENT_PROXY_ENABLED="1") == (
        0,
        ["mise trust --all --quiet in repo", "mise install in repo alone"],
    )


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_added_directory_gets_the_mise_tools_of_its_repos(
    add_directory: AddDirectory, tmp_path: Path
) -> None:
    added = tmp_path / "added"
    for name in ("first", "second"):
        (added / name).mkdir(parents=True)
        (added / name / ".tool-versions").write_text("")
    _, calls = add_directory(added, CCR_AGENT_PROXY_ENABLED="1")
    assert [call for call in calls if call.startswith("mise install")] == [
        "mise install in first alone",
        "mise install in second alone",
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_failed_mise_install_in_an_added_repo_fails_the_hook(
    add_directory: AddDirectory, tmp_path: Path
) -> None:
    repo = tmp_path / "added" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    status, _ = add_directory(
        repo, CCR_AGENT_PROXY_ENABLED="1", MISE_FAILS_AT="install repo"
    )
    assert status != 0


def test_added_repo_outside_the_cloud_gets_no_tools(
    add_directory: AddDirectory, tmp_path: Path
) -> None:
    repo = tmp_path / "added" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    assert add_directory(repo) == (0, [])


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_installs_only_missing_plugin_tools(
    set_up_tools: SetUpTools, home: Path
) -> None:
    register_every_plugin_tool(home)
    (home / "mise-installs").mkdir()
    (home / "mise-installs" / "gh").write_text("")
    _, calls = set_up_tools(CCR_AGENT_PROXY_ENABLED="1")
    installs = [call for call in calls if call.startswith("mise install ")]
    assert installs == [
        f"mise install {name} in home" for name in UP_FRONT_TOOLS if name != "gh"
    ]


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_cloud_session_prefers_installed_mise_tools_to_the_network(
    set_up_tools: SetUpTools, home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "projects" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    set_up_tools(CCR_AGENT_PROXY_ENABLED="1", CLAUDE_PROJECT_DIR=str(repo.parent))
    assert "mise install in repo alone" in (home / "calls").read_text()
    assert not (home / "online-mise-calls").exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_added_repo_waits_for_another_tool_install(
    add_directory: AddDirectory, home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "added" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    holder = hold_install_lock_for_a_second(home)
    _, calls = add_directory(repo, CCR_AGENT_PROXY_ENABLED="1")
    assert "mise install in repo alone" in calls
    assert_waited_for(holder, home)


@pytest.mark.skipif(os.geteuid() != 0, reason="cloud tools install only as root")
def test_added_repo_without_mise_says_so(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "added" / "repo"
    repo.mkdir(parents=True)
    (repo / "mise.toml").write_text("[tools]\n")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    result = subprocess.run(
        [sys.executable, HOOKS / "added_directory_tools.py"],
        input=json.dumps({"directory": str(repo)}),
        env={
            "HOME": str(home),
            "PATH": str(empty_bin),
            "CCR_AGENT_PROXY_ENABLED": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert (result.returncode, result.stderr) == (
        1,
        f"mise is not installed, so {repo} got none of its tools\n",
    )
