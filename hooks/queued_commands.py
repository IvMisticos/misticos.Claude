QUEUED_SUBCOMMANDS = {
    "dotnet": {"build", "test", "publish", "pack"},
    "cargo": {
        "build",
        "b",
        "check",
        "c",
        "test",
        "t",
        "bench",
        "clippy",
        "doc",
        "rustc",
        "nextest",
    },
    "bun": {"build", "test"},
    "uv": {"build"},
}
QUEUED_RUN_TARGETS = {
    "bun": {"build", "test"},
    "uv": {"pytest"},
}
PYTHON_LAUNCHERS = {"python", "python3"}
OPTIONS_WITH_VALUE = {
    "cargo": {"-C", "-Z", "--config", "--color"},
    "uv": {
        "--directory",
        "--project",
        "--cache-dir",
        "--config-file",
        "--color",
        "-w",
        "--with",
        "--with-editable",
        "--with-requirements",
        "-p",
        "--python",
        "--package",
        "--extra",
        "--group",
        "--env-file",
        "--index",
    },
    "bun": {"--cwd", "-c", "--config", "-F", "--filter", "--env-file", "--shell"},
}
WATCH_FLAGS = {"--watch", "--hot"}


def positionals(tool, arguments):
    options_with_value = OPTIONS_WITH_VALUE.get(tool, set())
    words = iter(arguments)
    for word in words:
        if word in options_with_value:
            next(words, None)
        elif not word.startswith(("-", "+")):
            yield word


def queues(tool, arguments):
    if WATCH_FLAGS & set(arguments):
        return False
    match list(positionals(tool, arguments)):
        case [subcommand, *_] if subcommand in QUEUED_SUBCOMMANDS.get(tool, ()):
            return True
        case ["run", launcher, target, *_] if launcher in PYTHON_LAUNCHERS:
            return target in QUEUED_RUN_TARGETS.get(tool, ())
        case ["run", target, *_]:
            return target in QUEUED_RUN_TARGETS.get(tool, ())
    return False
