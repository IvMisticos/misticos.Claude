import json
import subprocess
import sys
from pathlib import Path

import pytest
from json_values import JsonObject

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


@pytest.mark.parametrize(
    ("hook", "payload"),
    [
        pytest.param(
            "claude_model_cap.py",
            {"tool_name": "Agent", "tool_input": "explore"},
            id="claude",
        ),
        pytest.param("codex_model_cap.py", {"tool_input": "spawn"}, id="codex"),
    ],
)
def test_tool_input_that_is_not_an_object_is_left_alone(
    hook: str, payload: JsonObject
) -> None:
    result = subprocess.run(
        [sys.executable, HOOKS / hook],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode, result.stdout) == (0, "")
