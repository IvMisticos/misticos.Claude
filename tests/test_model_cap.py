import pytest
from json_values import JsonValue
from model_cap import outranks, parsed_model


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


def test_family_follows_the_tier_order() -> None:
    model = parsed_model("sol-opus")
    assert model is not None
    assert model.family == "opus"
