import io
import sys
from typing import NoReturn

import pytest
from hook_io import read_payload, run_hook


def test_undecodable_payload_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"a": "\xff"}')))
    assert read_payload() == {}


def test_crash_exits_quietly(capsys: pytest.CaptureFixture[str]) -> None:
    def crash() -> NoReturn:
        raise RuntimeError

    with pytest.raises(SystemExit) as exit_info:
        run_hook(crash)
    assert (exit_info.value.code, capsys.readouterr().out) == (0, "")
