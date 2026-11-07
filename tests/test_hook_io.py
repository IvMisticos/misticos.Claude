import io
import json
import sys
from typing import NoReturn

import pytest
from harnesses import OutputShape
from hook_io import (
    denied,
    pre_tool_use_output,
    read_payload,
    run_cursor_subagent_start,
    run_hook,
    run_pre_tool_use,
)
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


def test_crashing_subagent_check_lets_the_subagent_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", stdin_with(b"{}"))
    run_cursor_subagent_start(crashing_decider)
    written = capsys.readouterr()
    assert json.loads(written.out) == {"permission": "allow"}
    assert "RuntimeError" in written.err


def test_cursor_tool_denial_tells_the_agent_why() -> None:
    assert pre_tool_use_output(denied("Too big."), OutputShape.CURSOR) == {
        "permission": "deny",
        "user_message": "Too big.",
        "agent_message": "Too big.",
    }
