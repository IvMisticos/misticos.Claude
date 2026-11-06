import io
import sys

import pytest
from hook_io import read_payload


def test_undecodable_payload_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"a": "\xff"}')))
    assert read_payload() == {}
