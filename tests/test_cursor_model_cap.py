import io
import json
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"

import cursor_model_cap


def test_unreadable_payload_allows_the_spawn() -> None:
    result = subprocess.run(
        [sys.executable, HOOKS / "cursor_model_cap.py"],
        input=b"\xff\xfe",
        capture_output=True,
        check=True,
    )
    assert json.loads(result.stdout) == {"permission": "allow"}


def test_unexpected_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object) -> NoReturn:
        raise RuntimeError

    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(cursor_model_cap, "outranks", broken)
    with pytest.raises(RuntimeError):
        cursor_model_cap.main()
