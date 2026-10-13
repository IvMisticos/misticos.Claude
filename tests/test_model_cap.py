import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def tier_name_under_hash_seed(model: str, seed: int) -> str:
    script = f"from model_cap import tier_name; print(tier_name({model!r}))"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=HOOKS,
        env={"PYTHONHASHSEED": str(seed)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_tier_name_does_not_depend_on_hash_order() -> None:
    names = {tier_name_under_hash_seed("opus-sol", seed) for seed in range(16)}
    assert len(names) == 1
