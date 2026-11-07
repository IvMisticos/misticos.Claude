import os
import subprocess
import sys
from pathlib import Path

from json_values import dict_or_empty, json_object_in
from plugin_paths import DATA_ROOT

WEB_GUIDANCE_NAME = "modern-web-guidance"
WEB_GUIDANCE_PLUGIN = f"{WEB_GUIDANCE_NAME}@googlechrome"
WEB_GUIDANCE_MARKETPLACE = "GoogleChrome/modern-web-guidance"
INSTALLED_PLUGINS = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
PLUGIN_DATA = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or DATA_ROOT)
WEB_GUIDANCE_OFFERED = PLUGIN_DATA / "web-guidance-offered"


def web_guidance_plugin_is_installed() -> bool:
    installed = json_object_in(INSTALLED_PLUGINS)
    return WEB_GUIDANCE_PLUGIN in dict_or_empty(installed.get("plugins"))


def install_web_guidance_plugin() -> None:
    subprocess.run(
        (
            "claude",
            "plugin",
            "install",
            WEB_GUIDANCE_NAME,
            "--marketplace",
            WEB_GUIDANCE_MARKETPLACE,
            "--scope",
            "user",
        ),
        check=True,
        stdout=sys.stderr,
    )


def offer_web_guidance_plugin(user_choice: bool | None) -> None:
    if user_choice is False or WEB_GUIDANCE_OFFERED.exists():
        return
    if web_guidance_plugin_is_installed():
        return
    install_web_guidance_plugin()
    WEB_GUIDANCE_OFFERED.parent.mkdir(parents=True, exist_ok=True)
    WEB_GUIDANCE_OFFERED.touch()
