import json
import subprocess
import sys

from conftest import ROOT, json_at, run_json_hook, text_at
from json_values import JsonObject

CURSOR_MODEL_CAP = ROOT / "hooks" / "cursor_model_cap.py"


def test_unreadable_payload_allows_the_spawn() -> None:
    result = subprocess.run(
        [sys.executable, CURSOR_MODEL_CAP],
        input=b"\xff\xfe",
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"permission": "allow"}


def test_denies_a_subagent_above_the_caller() -> None:
    payload: JsonObject = {
        "model": "claude-sonnet-4-5",
        "subagent_model": "claude-opus-4-1",
        "subagent_type": "explore",
    }
    output = run_json_hook(CURSOR_MODEL_CAP, payload)
    assert json_at(output, "permission") == "deny"
    assert text_at(output, "user_message") == (
        "Blocked subagent explore on claude-opus-4-1, "
        "above the caller's claude-sonnet-4-5. "
        "Pick one at or below claude-sonnet-4-5."
    )
