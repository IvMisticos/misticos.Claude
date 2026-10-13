import json
import os
import shutil
import subprocess

import pytest
from conftest import ROOT

WEB_GUIDANCE_PLUGIN = "modern-web-guidance@googlechrome"


def unshimmed_uv():
    directories = os.environ["PATH"].split(os.pathsep)
    unshimmed = [
        directory for directory in directories if not directory.endswith("shims")
    ]
    uv = shutil.which("uv", path=os.pathsep.join(unshimmed))
    if uv is None:
        pytest.skip("needs uv")
    return uv


@pytest.fixture
def configure_settings(home, fake_bin):
    uv = unshimmed_uv()
    bin_dir = fake_bin("placeholder", "")
    settings_path = home / ".claude" / "settings.json"

    def configure(settings):
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings))
        subprocess.run(
            [uv, "run", "--script", ROOT / "hooks" / "setup_settings.py"],
            env={**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"},
            check=True,
            timeout=120,
        )
        return json.loads(settings_path.read_text())["enabledPlugins"]

    return configure


def test_lost_plugin_entry_comes_back(configure_settings):
    assert configure_settings({})[WEB_GUIDANCE_PLUGIN] is True


def test_user_choice_for_the_plugin_wins(configure_settings):
    settings = {"enabledPlugins": {WEB_GUIDANCE_PLUGIN: False}}
    assert configure_settings(settings)[WEB_GUIDANCE_PLUGIN] is False
