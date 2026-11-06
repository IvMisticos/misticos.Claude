import io
import sys
from typing import NoReturn

import pytest
from harnesses import OutputShape
from hook_io import read_payload, run_hook, run_pre_tool_use
from json_values import JsonObject


def stdin_with(payload: bytes) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(payload))


def crashing_decider(_: JsonObject) -> NoReturn:
    raise RuntimeError


def test_undecodable_payload_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", stdin_with(b'{"a": "\xff"}'))
    assert read_payload() == {}


def test_crash_exits_quietly(capsys: pytest.CaptureFixture[str]) -> None:
    def crash() -> NoReturn:
        raise RuntimeError

    with pytest.raises(SystemExit) as exit_info:
        run_hook(crash)
    assert (exit_info.value.code, capsys.readouterr().out) == (0, "")


@pytest.mark.parametrize(
    ("shape", "output"),
    [
        pytest.param(OutputShape.CLAUDE, "", id="claude"),
        pytest.param(OutputShape.CURSOR, '{"permission": "allow"}', id="cursor"),
    ],
)
def test_crashing_decider_lets_the_tool_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    shape: OutputShape,
    output: str,
) -> None:
    monkeypatch.setattr(sys, "stdin", stdin_with(b"{}"))
    run_pre_tool_use(crashing_decider, shape)
    written = capsys.readouterr()
    assert written.out == output
    assert "RuntimeError" in written.err
