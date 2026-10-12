import argparse
from enum import Enum, auto
from typing import NamedTuple


class ContextSource(Enum):
    TRANSCRIPT = auto()
    SIZE = auto()
    PAYLOAD = auto()


class OutputShape(Enum):
    CLAUDE = auto()
    CURSOR = auto()


class ReplyHistory(Enum):
    TRANSCRIPT = auto()
    EVENTS = auto()


class Harness(NamedTuple):
    model_names: dict[str, str]
    context_from: ContextSource
    output_shape: OutputShape
    reply_history: ReplyHistory = ReplyHistory.EVENTS


HARNESSES = {
    "claude": Harness(
        model_names={
            "cheap": "Haiku",
            "fast": "Sonnet",
            "strong": "Opus",
            "lead": "Fable",
        },
        context_from=ContextSource.TRANSCRIPT,
        output_shape=OutputShape.CLAUDE,
        reply_history=ReplyHistory.TRANSCRIPT,
    ),
    "codex": Harness(
        model_names={"fast": "Luna", "strong": "Sol", "lead": "Astra"},
        context_from=ContextSource.SIZE,
        output_shape=OutputShape.CLAUDE,
    ),
    "cursor": Harness(
        model_names={
            "fast": "Sonnet or Luna",
            "strong": "Opus or Sol",
            "lead": "Fable or Astra",
        },
        context_from=ContextSource.PAYLOAD,
        output_shape=OutputShape.CURSOR,
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
