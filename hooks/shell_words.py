from typing import NamedTuple

SHELL_OPERATOR_CHARACTERS = "();<>|&\n"
REDIRECTION_CHARACTERS = "<>"
WORD_SEPARATORS = " \t\r"
LINE_CONTINUATION = "\\\n"
DOUBLE_QUOTE_ESCAPES = frozenset('$`"\\')
ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}


class UnterminatedQuoteError(ValueError):
    pass


class ShellOperator(NamedTuple):
    text: str


class ShellWords:
    def __init__(self, text):
        self.text = text
        self.index = 0
        self.word = None

    def __iter__(self):
        while self.index < len(self.text):
            yield from self.next_tokens()
        yield from self.finished_word()

    def next_tokens(self):
        character = self.text[self.index]
        if character in WORD_SEPARATORS:
            self.index += 1
            return self.finished_word()
        if character in SHELL_OPERATOR_CHARACTERS:
            return self.operator_tokens()
        if character == "#" and self.word is None:
            self.skip_comment()
            return []
        if self.text.startswith(LINE_CONTINUATION, self.index):
            self.index += len(LINE_CONTINUATION)
            return []
        self.append(self.word_part())
        return []

    def finished_word(self):
        word, self.word = self.word, None
        return [] if word is None else [word]

    def append(self, part):
        self.word = (self.word or "") + part

    def is_file_descriptor(self):
        return self.word is not None and self.word.isdigit()

    def operator_tokens(self):
        if (
            self.text[self.index] in REDIRECTION_CHARACTERS
            and self.is_file_descriptor()
        ):
            self.word = None
        tokens = self.finished_word()
        start = self.index
        while self.at_any_of(SHELL_OPERATOR_CHARACTERS):
            self.index += 1
        return [*tokens, ShellOperator(self.text[start : self.index])]

    def at_any_of(self, characters):
        return self.index < len(self.text) and self.text[self.index] in characters

    def skip_comment(self):
        end = self.text.find("\n", self.index)
        self.index = len(self.text) if end < 0 else end

    def word_part(self):
        if self.text.startswith("$'", self.index):
            self.index += 2
            return self.ansi_c_quoted()
        character = self.text[self.index]
        self.index += 1
        if character == "\\":
            return self.escaped_character()
        if character == "'":
            return self.single_quoted()
        if character == '"':
            return self.double_quoted()
        return character

    def escaped_character(self):
        character = self.text[self.index : self.index + 1]
        self.index += 1
        return character

    def single_quoted(self):
        end = self.text.find("'", self.index)
        if end < 0:
            raise UnterminatedQuoteError
        value = self.text[self.index : end]
        self.index = end + 1
        return value

    def double_quoted(self):
        return self.quoted('"', self.double_quote_escape)

    def ansi_c_quoted(self):
        return self.quoted("'", self.ansi_c_escape)

    def quoted(self, closing_quote, escape):
        value = []
        while self.index < len(self.text):
            character = self.text[self.index]
            self.index += 1
            if character == closing_quote:
                return "".join(value)
            value.append(
                escape(self.escaped_character()) if character == "\\" else character
            )
        raise UnterminatedQuoteError

    @staticmethod
    def double_quote_escape(character):
        if character == "\n":
            return ""
        return character if character in DOUBLE_QUOTE_ESCAPES else "\\" + character

    @staticmethod
    def ansi_c_escape(character):
        return ANSI_C_ESCAPES.get(character, "\\" + character)


def shell_tokens(text):
    try:
        return list(ShellWords(text))
    except UnterminatedQuoteError:
        return []
