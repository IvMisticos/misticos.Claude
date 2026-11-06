import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

import pytest
import setup_settings
from conftest import (
    ROOT,
    FakeBin,
    claude_hook_commands,
    json_at,
    plugin_hook_command,
    without_session_variables,
)
from json_values import JsonObject, JsonValue

HOOKS = ROOT / "hooks"
WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"
ENABLED_PLUGINS = {
    WEB_GUIDANCE_PLUGIN: True,
    "chosen-off@elsewhere": False,
}
INSTALL = (
    "claude plugin install modern-web-guidance"
    " --marketplace GoogleChrome/modern-web-guidance --scope user"
)
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

home = Path(os.environ["HOME"])
with (home / "calls").open("a") as calls:
    calls.write(" ".join(["claude", *sys.argv[1:]]) + "\\n")
if os.environ.get("PLUGIN_INSTALL_FAILS"):
    sys.exit(1)
settings_path = home / ".claude" / "settings.json"
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
settings.setdefault("enabledPlugins", {})[sys.argv[3] + "@googlechrome"] = True
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(settings))
"""


class ConfigureSettings(Protocol):
    def __call__(
        self, check: bool = True, **extra_environment: str
    ) -> subprocess.CompletedProcess[bytes]: ...


def unshimmed_uv() -> str:
    directories = os.environ["PATH"].split(os.pathsep)
    unshimmed = [
        directory for directory in directories if not directory.endswith("shims")
    ]
    uv = shutil.which("uv", path=os.pathsep.join(unshimmed))
    if uv is None:
        pytest.skip("needs uv")
    return uv


@pytest.fixture(scope="module")
def uv_environment() -> tuple[str, dict[str, str]]:
    uv = unshimmed_uv()
    cache_dir = subprocess.run(
        [uv, "cache", "dir"], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    environment = {**without_session_variables(os.environ), "UV_CACHE_DIR": cache_dir}
    probe = subprocess.run(
        [
            uv,
            "run",
            "--no-project",
            "--with",
            "tomli-w",
            "python",
            "-c",
            "import tomli_w",
        ],
        env=environment,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if probe.returncode != 0:
        pytest.skip("cannot fetch tomli-w")
    return uv, environment


@pytest.fixture
def configure_settings(
    home: Path, fake_bin: FakeBin, uv_environment: tuple[str, dict[str, str]]
) -> ConfigureSettings:
    uv, environment = uv_environment
    bin_dir = fake_bin("claude", FAKE_CLAUDE)

    def configure(
        check: bool = True, **extra_environment: str
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [uv, "run", "--script", HOOKS / "setup_settings.py"],
            env={
                **environment,
                "HOME": str(home),
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                **extra_environment,
            },
            capture_output=True,
            check=check,
            timeout=120,
        )

    return configure


def claude_calls(home: Path) -> list[str]:
    calls = home / "calls"
    return calls.read_text().splitlines() if calls.exists() else []


def written_setting(home: Path, *keys: str) -> JsonValue:
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    return json_at(settings, *keys)


def write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_second_run_writes_nothing(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"enabledPlugins": ENABLED_PLUGINS}))
    configure_settings()
    first_write = settings_path.stat().st_mtime_ns
    configure_settings()
    assert settings_path.stat().st_mtime_ns == first_write
    enabled = json.loads(settings_path.read_text())["enabledPlugins"]
    assert enabled.items() >= ENABLED_PLUGINS.items()


@pytest.mark.parametrize(
    "stored", ["{not json", "[]", json.dumps({"enabledPlugins": [1]})]
)
def test_malformed_settings_fail_the_hook_once_and_stay_untouched(
    configure_settings: ConfigureSettings, home: Path, stored: str
) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(stored)
    result = configure_settings(check=False)
    assert result.returncode == 1
    assert result.stderr.count(b"Traceback") == 1
    assert claude_calls(home) == []
    assert settings_path.read_text() == stored


def test_settings_hook_runs_every_session() -> None:
    assert claude_hook_commands("SessionStart", "setup_settings.py") == [
        plugin_hook_command("setup_settings.py")
    ]


@pytest.mark.parametrize(
    "settings",
    [
        {"permissions": ["Bash"]},
        {"permissions": {"deny": "Bash"}},
        {"skillOverrides": "x"},
        {"enabledPlugins": 1},
        {"extraKnownMarketplaces": []},
        {"extraKnownMarketplaces": {"misticos": "x"}},
        {"env": ["A=1"]},
    ],
)
def test_malformed_claude_settings_stay_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: JsonObject
) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(setup_settings, "CLAUDE_SETTINGS", settings_path)
    stored = json.dumps(settings)
    settings_path.write_text(stored)
    with pytest.raises(TypeError):
        setup_settings.configure_claude_settings()
    assert settings_path.read_text() == stored


@pytest.mark.parametrize(
    "settings",
    [
        {"permissions": None},
        {"permissions": {"deny": None}},
        {"skillOverrides": None},
        {"enabledPlugins": None},
        {"extraKnownMarketplaces": None},
        {"env": None},
    ],
)
def test_null_claude_settings_count_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: JsonObject
) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(setup_settings, "CLAUDE_SETTINGS", settings_path)
    settings_path.write_text(json.dumps(settings))
    setup_settings.configure_claude_settings()
    written = json.loads(settings_path.read_text())
    assert written["permissions"]["deny"] == list(setup_settings.DENIED_TOOLS)


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, {"source": setup_settings.OWN_MARKETPLACE_SOURCE, "autoUpdate": True}),
        (
            {"misticos": {"source": {"source": "directory", "path": "/src"}}},
            {"source": {"source": "directory", "path": "/src"}, "autoUpdate": True},
        ),
        (
            {
                "misticos": {
                    "source": setup_settings.OWN_MARKETPLACE_SOURCE,
                    "autoUpdate": False,
                }
            },
            {"source": setup_settings.OWN_MARKETPLACE_SOURCE, "autoUpdate": False},
        ),
    ],
)
def test_own_marketplace_auto_updates_unless_turned_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: JsonObject,
    expected: JsonObject,
) -> None:
    other = {"source": {"source": "github", "repo": "GoogleChrome/modern-web-guidance"}}
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(setup_settings, "CLAUDE_SETTINGS", settings_path)
    settings_path.write_text(
        json.dumps({"extraKnownMarketplaces": {**settings, "googlechrome": other}})
    )
    setup_settings.configure_claude_settings()
    marketplaces = json.loads(settings_path.read_text())["extraKnownMarketplaces"]
    assert marketplaces == {"misticos": expected, "googlechrome": other}


def test_plugin_install_lands_in_the_applied_settings(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    configure_settings()
    assert claude_calls(home) == [INSTALL]
    assert written_setting(home, "enabledPlugins", WEB_GUIDANCE_PLUGIN) is True
    assert written_setting(home, "autoMemoryEnabled") is False


def test_failed_plugin_install_still_applies_settings(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    result = configure_settings(check=False, PLUGIN_INSTALL_FAILS="1")
    assert result.returncode != 0
    assert claude_calls(home) == [INSTALL]
    assert written_setting(home, "autoMemoryEnabled") is False


def test_plugin_is_offered_once(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    configure_settings()
    configure_settings()
    assert claude_calls(home) == [INSTALL]


def test_plugin_is_offered_again_after_a_failed_install(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    configure_settings(check=False, PLUGIN_INSTALL_FAILS="1")
    configure_settings()
    assert claude_calls(home) == [INSTALL, INSTALL]


def test_plugin_is_offered_once_per_plugin_data(
    configure_settings: ConfigureSettings, home: Path, tmp_path: Path
) -> None:
    configure_settings(CLAUDE_PLUGIN_DATA=str(tmp_path / "old-data"))
    configure_settings(CLAUDE_PLUGIN_DATA=str(tmp_path / "new-data"))
    assert claude_calls(home) == [INSTALL, INSTALL]


def test_installed_plugin_is_left_alone(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    installed = home / ".claude" / "plugins" / "installed_plugins.json"
    write_json(installed, {"plugins": {WEB_GUIDANCE_PLUGIN: []}})
    configure_settings()
    assert claude_calls(home) == []


def test_plugin_the_user_disabled_is_not_installed(
    configure_settings: ConfigureSettings, home: Path
) -> None:
    settings = home / ".claude" / "settings.json"
    write_json(settings, {"enabledPlugins": {WEB_GUIDANCE_PLUGIN: False}})
    configure_settings()
    assert claude_calls(home) == []
    assert written_setting(home, "enabledPlugins", WEB_GUIDANCE_PLUGIN) is False
