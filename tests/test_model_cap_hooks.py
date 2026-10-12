import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


@pytest.mark.parametrize(
    ("hook", "malformed_payload"),
    [
        pytest.param("claude_model_cap.py", {"tool_name": "Agent", "agent_id": "a1"}),
        pytest.param("codex_model_cap.py", {"tool_input": "spawn"}),
    ],
)
def test_crash_exits_quietly(hook, malformed_payload):
    result = subprocess.run(
        [sys.executable, HOOKS / hook],
        input=json.dumps(malformed_payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode, result.stdout) == (0, "")
