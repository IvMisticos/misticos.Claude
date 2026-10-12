import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))

import cursor_model_cap


def test_unreadable_payload_allows_the_spawn():
    result = subprocess.run(
        [sys.executable, HOOKS / "cursor_model_cap.py"],
        input=b"\xff\xfe",
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"permission": "allow"}


def test_unexpected_error_is_not_hidden(monkeypatch):
    def broken(*_):
        raise RuntimeError

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(cursor_model_cap, "outranks", broken)
    with pytest.raises(RuntimeError):
        cursor_model_cap.main()
