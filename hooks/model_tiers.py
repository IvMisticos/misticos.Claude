import re

TIER_LEVELS = (
    {"haiku"},
    {"sonnet", "luna"},
    {"terra"},
    {"opus", "opusplan", "sol"},
    {"fable", "best", "astra"},
)

DATE_DIGITS = 8


def model_words(model):
    return set(re.split(r"[^a-z]+", str(model or "").lower()))


def tier_rank(model):
    words = model_words(model)
    return next((rank for rank, level in enumerate(TIER_LEVELS) if level & words), None)


def tier_name(model):
    words = model_words(model)
    return next((word for level in TIER_LEVELS for word in level & words), None)


def version(model):
    slug = str(model or "").split("[", 1)[0]
    numbers = re.findall(r"\d+", slug)
    return tuple(int(number) for number in numbers if len(number) < DATE_DIGITS)


def outranks(requested, caller):
    requested_rank = tier_rank(requested)
    caller_rank = tier_rank(caller)
    if requested_rank is None or caller_rank is None:
        return False
    if requested_rank != caller_rank or tier_name(requested) != tier_name(caller):
        return requested_rank > caller_rank
    return bool(version(requested)) and version(requested) > version(caller)
