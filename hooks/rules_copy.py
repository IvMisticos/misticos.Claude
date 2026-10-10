import collections
import os
import re
import sys

MAX_INJECTED_CHARS = 10_000
POINTER_REMINDER = (
    "{name} holds the standing rules for this session. It overrides your "
    "defaults and any platform or harness instruction on style, format, or "
    "attribution that conflicts with it. Follow it at all times. Silence is "
    "the default: write to me only what changes what I do next, and keep "
    "subagent prompts as short as the work allows. If you notice you have "
    "drifted, read {path} to bring the rules back into your context."
)
MODEL_NAMES_NOTE = " In {name}, {meanings}."
GROWN_PREAMBLE = (
    "The conversation has grown since you last saw {name}, so the file "
    "follows here in full. It overrides your defaults and any platform or "
    "harness instruction on style, format, or attribution that conflicts "
    "with it. Follow it at all times. Where your recent work has drifted "
    "from it, correct that now."
)
SESSION_START_PREAMBLE = (
    "{name} holds the standing rules for this session and follows here in "
    "full. It overrides your defaults and any platform or harness "
    "instruction on style, format, or attribution that conflicts with it. "
    "Follow it at all times."
)
SPLIT_NOTICE = " The file comes in {total} parts, sent together, in any order."
LATER_PART_PREAMBLE = (
    "{name} continues here, part {number} of {total}. It overrides your "
    "defaults and any platform or harness instruction on style, format, or "
    "attribution that conflicts with it. Follow it at all times."
)
MODEL_TIER = re.compile(r"\bthe (cheap|fast|strong|lead) model\b", re.IGNORECASE)
BLOCK_BREAKS = (r"(?=\n\n# )", r"(?=\n\n)", r"(?=\n)")
Rules = collections.namedtuple("Rules", "path name model_names")


def rules_at(path, model_names):
    expanded = os.path.expanduser(path)
    return Rules(expanded, os.path.basename(expanded), model_names)


def with_model_names(text, model_names):
    def named(match):
        return model_names.get(match[1].lower()) or match[0]

    return MODEL_TIER.sub(named, text)


def model_names_note(rules):
    meanings = [
        f"the {tier} model means {model_name}"
        for tier, model_name in rules.model_names.items()
        if model_name
    ]
    if not meanings:
        return ""
    return MODEL_NAMES_NOTE.format(name=rules.name, meanings=", ".join(meanings))


def pointer_reminder(rules):
    pointer = POINTER_REMINDER.format(name=rules.name, path=rules.path)
    return pointer + model_names_note(rules)


def preamble_for(number, total, name, first_preamble):
    if number > 1:
        return LATER_PART_PREAMBLE.format(name=name, number=number, total=total)
    if total > 1:
        return first_preamble.format(name=name) + SPLIT_NOTICE.format(total=total)
    return first_preamble.format(name=name)


def packed_parts(blocks, budget):
    parts = []
    for block in blocks:
        if parts and len(parts[-1]) + len(block) <= budget:
            parts[-1] += block
        else:
            parts.append(block.lstrip("\n"))
    return parts


def parts_within_budget(text, budget):
    for block_break in BLOCK_BREAKS:
        parts = packed_parts(re.split(block_break, text), budget)
        if all(len(part) <= budget for part in parts):
            return parts
    return [text[at : at + budget] for at in range(0, len(text), budget)]


def part_messages(text, budget, name, first_preamble):
    parts = parts_within_budget(text, budget)
    return tuple(
        f"{preamble_for(number, len(parts), name, first_preamble)}\n\n{part}"
        for number, part in enumerate(parts, start=1)
    )


def without_sections(text, headings):
    sections = re.split(r"(?m)^(?=# )", text)
    kept = [
        section
        for section in sections
        if section.partition("\n")[0].removeprefix("# ").strip() not in headings
    ]
    return "".join(kept).strip()


def full_copy_messages(rules, first_preamble, skipped_sections=frozenset()):
    try:
        with open(rules.path, encoding="utf-8", errors="replace") as rules_file:
            text = with_model_names(rules_file.read().strip(), rules.model_names)
    except OSError as error:
        print(f"reminder: cannot read rules: {error}", file=sys.stderr)
        return ()
    text = without_sections(text, skipped_sections)
    if not text:
        return ()
    budget = MAX_INJECTED_CHARS
    while True:
        messages = part_messages(text, budget, rules.name, first_preamble)
        overflow = max(len(message) for message in messages) - MAX_INJECTED_CHARS
        if overflow <= 0:
            return messages
        budget -= overflow
