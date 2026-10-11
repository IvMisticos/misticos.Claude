import argparse
from typing import NamedTuple


class Harness(NamedTuple):
    model_names: dict
    context_from: str
    output_shape: str
    skipped_agent_types: frozenset = frozenset()


HARNESSES = {
    "claude": Harness(
        model_names={
            "cheap": "Haiku",
            "fast": "Sonnet",
            "strong": "Opus",
            "lead": "Fable",
        },
        context_from="transcript",
        output_shape="claude",
        skipped_agent_types=frozenset({"misticos:scout"}),
    ),
    "codex": Harness(
        model_names={"fast": "Luna", "strong": "Sol", "lead": "Astra"},
        context_from="size",
        output_shape="claude",
    ),
    "cursor": Harness(
        model_names={
            "fast": "Sonnet or Luna",
            "strong": "Opus or Sol",
            "lead": "Fable or Astra",
        },
        context_from="payload",
        output_shape="cursor",
    ),
}


def harness_named(name):
    try:
        return HARNESSES[name]
    except KeyError:
        raise argparse.ArgumentTypeError(f"unknown harness: {name}") from None


class QuietArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def harness_parser():
    parser = QuietArgumentParser(add_help=False)
    parser.add_argument("--harness", type=harness_named, default=HARNESSES["claude"])
    return parser
