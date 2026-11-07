from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import NamedTuple

OPTIONS_END = "--"
PR_COMMAND = "pr"
CREATE_SUBCOMMANDS = frozenset({"create", "new"})
FALSE_WORDS = frozenset({"0", "f", "F", "false", "FALSE", "False"})


class Flag(NamedTuple):
    name: str
    short: str | None
    takes_value: bool


def switch(name: str, short: str | None = None) -> Flag:
    return Flag(name, short, takes_value=False)


def valued(name: str, short: str | None = None) -> Flag:
    return Flag(name, short, takes_value=True)


class FlagTable(NamedTuple):
    by_name: Mapping[str, Flag]
    by_short: Mapping[str, Flag]
    unknown_flags_take_values: bool

    def long_flag(self, name: str) -> Flag:
        unknown = Flag(name, None, self.unknown_flags_take_values)
        return self.by_name.get(name, unknown)

    def short_flag(self, letter: str, alone: bool) -> Flag:
        unknown = Flag(letter, letter, self.unknown_flags_take_values and alone)
        return self.by_short.get(letter, unknown)


def flag_table(flags: Iterable[Flag], unknown_flags_take_values: bool) -> FlagTable:
    listed = (*flags, switch("help", "h"))
    return FlagTable(
        {flag.name: flag for flag in listed},
        {flag.short: flag for flag in listed if flag.short},
        unknown_flags_take_values,
    )


PR_FLAGS = (valued("repo", "R"),)
PR_BODY_FLAGS = (valued("body", "b"), valued("body-file", "F"))
CREATE_FLAGS = (
    *PR_FLAGS,
    *PR_BODY_FLAGS,
    valued("assignee", "a"),
    valued("attach"),
    valued("base", "B"),
    switch("draft", "d"),
    switch("dry-run"),
    switch("editor", "e"),
    switch("fill", "f"),
    switch("fill-first"),
    switch("fill-verbose"),
    valued("head", "H"),
    valued("label", "l"),
    valued("milestone", "m"),
    switch("no-maintainer-edit"),
    valued("project", "p"),
    valued("recover"),
    valued("reviewer", "r"),
    valued("template", "T"),
    valued("title", "t"),
    switch("web", "w"),
)
COMMAND_FLAGS: dict[tuple[str, ...], tuple[Flag, ...]] = {
    ("api",): (
        switch("allow-escape-sequences"),
        valued("cache"),
        valued("field", "F"),
        valued("header", "H"),
        valued("hostname"),
        switch("include", "i"),
        valued("input"),
        valued("jq", "q"),
        valued("method", "X"),
        switch("paginate"),
        valued("preview", "p"),
        valued("raw-field", "f"),
        switch("silent"),
        switch("slurp"),
        valued("template", "t"),
        switch("verbose"),
    ),
    **{(PR_COMMAND, create): CREATE_FLAGS for create in CREATE_SUBCOMMANDS},
    ("pr", "edit"): (
        *PR_FLAGS,
        *PR_BODY_FLAGS,
        valued("add-assignee"),
        valued("add-label"),
        valued("add-project"),
        valued("add-reviewer"),
        valued("attach"),
        valued("base", "B"),
        valued("milestone", "m"),
        valued("remove-assignee"),
        valued("remove-label"),
        switch("remove-milestone"),
        valued("remove-project"),
        valued("remove-reviewer"),
        valued("title", "t"),
    ),
    ("pr", "ready"): (*PR_FLAGS, switch("undo")),
    ("pr", "close"): (*PR_FLAGS, valued("comment", "c"), switch("delete-branch", "d")),
    ("pr", "reopen"): (*PR_FLAGS, valued("comment", "c")),
    ("pr", "merge"): (
        *PR_FLAGS,
        *PR_BODY_FLAGS,
        switch("admin"),
        valued("author-email", "A"),
        switch("auto"),
        switch("delete-branch", "d"),
        switch("disable-auto"),
        valued("match-head-commit"),
        switch("merge", "m"),
        switch("rebase", "r"),
        switch("squash", "s"),
        valued("subject", "t"),
    ),
    ("pr", "update-branch"): (*PR_FLAGS, switch("rebase")),
    ("pr", "review"): (
        *PR_FLAGS,
        *PR_BODY_FLAGS,
        switch("approve", "a"),
        switch("comment", "c"),
        switch("request-changes", "r"),
    ),
    ("pr", "comment"): (
        *PR_FLAGS,
        *PR_BODY_FLAGS,
        valued("attach"),
        switch("create-if-none"),
        switch("delete-last"),
        switch("edit-last"),
        switch("editor", "e"),
        switch("web", "w"),
        switch("yes"),
    ),
}
COMMAND_FLAG_TABLES = {
    command: flag_table(flags, unknown_flags_take_values=False)
    for command, flags in COMMAND_FLAGS.items()
}
UNLISTED_PR_COMMAND_FLAGS = flag_table(PR_FLAGS, unknown_flags_take_values=True)
UNLISTED_COMMAND_FLAGS = flag_table((), unknown_flags_take_values=True)


class Option(NamedTuple):
    name: str
    value: str | bool


class Positional(NamedTuple):
    index: int
    word: str


class OptionsEnd(NamedTuple):
    pass


type Parsed = Option | Positional | OptionsEnd


class GhArguments(NamedTuple):
    command: tuple[str, ...]
    positionals: tuple[str, ...]
    options: tuple[Option, ...]

    def values(self, name: str) -> list[str]:
        return [
            option.value
            for option in self.options
            if option.name == name and isinstance(option.value, str)
        ]

    def last_value(self, name: str) -> str | None:
        values = self.values(name)
        return values[-1] if values else None

    def given_flags(self) -> frozenset[str]:
        last_values = {option.name: option.value for option in self.options}
        return frozenset(
            name for name, value in last_values.items() if value is not False
        )


def switch_value(text: str) -> bool:
    return text not in FALSE_WORDS


def option(flag: Flag, value: str) -> Option:
    return Option(flag.name, value if flag.takes_value else switch_value(value))


def next_word(words: Iterator[tuple[int, str]]) -> str:
    return next(words, (0, ""))[1]


def long_option(
    word: str, table: FlagTable, words: Iterator[tuple[int, str]]
) -> Option:
    name, has_value, value = word.removeprefix("--").partition("=")
    flag = table.long_flag(name)
    if has_value:
        return option(flag, value)
    if flag.takes_value:
        return Option(flag.name, next_word(words))
    return Option(flag.name, True)


def short_options(
    word: str, table: FlagTable, words: Iterator[tuple[int, str]]
) -> Iterator[Option]:
    letters = word.removeprefix("-")
    for position, letter in enumerate(letters):
        flag = table.short_flag(letter, alone=len(letters) == 1)
        rest = letters[position + 1 :]
        if rest.startswith("="):
            yield option(flag, rest.removeprefix("="))
            return
        if flag.takes_value:
            yield Option(flag.name, rest or next_word(words))
            return
        yield Option(flag.name, True)


def parsed_words(words: Sequence[str], table: FlagTable) -> Iterator[Parsed]:
    remaining = iter(enumerate(words))
    for index, word in remaining:
        if word == OPTIONS_END:
            yield OptionsEnd()
            yield from (Positional(*rest) for rest in remaining)
        elif word.startswith("--"):
            yield long_option(word, table, remaining)
        elif word.startswith("-") and word != "-":
            yield from short_options(word, table, remaining)
        else:
            yield Positional(index, word)


def command_positions(words: Sequence[str]) -> list[Positional]:
    found: list[Positional] = []
    for parsed in parsed_words(words, UNLISTED_COMMAND_FLAGS):
        if isinstance(parsed, OptionsEnd):
            break
        if not isinstance(parsed, Positional) or not parsed.word:
            continue
        found.append(parsed)
        if found[0].word != PR_COMMAND or len(found) == 2:
            break
    return found


def command_flags(command: tuple[str, ...]) -> FlagTable:
    if command in COMMAND_FLAG_TABLES:
        return COMMAND_FLAG_TABLES[command]
    if command[:1] == (PR_COMMAND,):
        return UNLISTED_PR_COMMAND_FLAGS
    return UNLISTED_COMMAND_FLAGS


def gh_arguments(arguments: Sequence[str]) -> GhArguments:
    positions = command_positions(arguments)
    command = tuple(position.word for position in positions)
    command_indexes = {position.index for position in positions}
    rest = [
        word for index, word in enumerate(arguments) if index not in command_indexes
    ]
    parsed = list(parsed_words(rest, command_flags(command)))
    return GhArguments(
        command,
        tuple(item.word for item in parsed if isinstance(item, Positional)),
        tuple(item for item in parsed if isinstance(item, Option)),
    )
