import subprocess
import sys
from pathlib import Path

import pytest
from json_values import JsonValue
from model_cap import outranks, parsed_model

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


@pytest.mark.parametrize(
    ("requested", "caller", "expected"),
    [
        pytest.param("claude-opus-4-5", "claude-sonnet-4-5", True, id="higher-tier"),
        pytest.param("claude-haiku-4-5", "claude-sonnet-4-5", False, id="lower-tier"),
        pytest.param("gpt-5-sol", "claude-opus-4-5", False, id="same-tier"),
        pytest.param("claude-opus-4-6", "claude-opus-4-5", True, id="newer"),
        pytest.param("claude-opus-4-1", "claude-opus-4-5", False, id="older"),
        pytest.param("opus", "claude-opus-4-5", False, id="alias-to-versioned"),
        pytest.param("claude-opus-4-6", "opus", True, id="versioned-to-alias"),
        pytest.param(
            "claude-sonnet-4-5-20250929", "claude-sonnet-4-5", False, id="snapshot"
        ),
        pytest.param("claude-opus-4-6[1m]", "claude-opus-4-6", False, id="1m"),
        pytest.param("gpt-5", "claude-haiku-4-5", False, id="unknown-requested"),
        pytest.param("claude-opus-4-5", "gpt-5", False, id="unknown-caller"),
        pytest.param({"a": "opus"}, "claude-haiku-4-5", False, id="non-string"),
    ],
)
def test_outranks(requested: JsonValue, caller: JsonValue, expected: bool) -> None:
    assert outranks(parsed_model(requested), parsed_model(caller)) is expected


def family_under_hash_seed(model: str, seed: int) -> str:
    script = (
        f"from model_cap import parsed_model; print(parsed_model({model!r}).family)"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=HOOKS,
        env={"PYTHONHASHSEED": str(seed)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_family_follows_the_tier_order_under_any_hash_seed() -> None:
    families = {family_under_hash_seed("sol-opus", seed) for seed in range(16)}
    assert families == {"opus\n"}
