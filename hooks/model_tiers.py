import re

TIER_LEVELS = (
    {"haiku"},
    {"sonnet", "luna"},
    {"terra"},
    {"opus", "opusplan", "sol"},
    {"fable", "best", "astra"},
)


def model_words(model):
    return set(re.split(r"[^a-z]+", str(model or "").lower()))


def tier_rank(model):
    words = model_words(model)
    return next((rank for rank, level in enumerate(TIER_LEVELS) if level & words), None)


def tier_name(model):
    words = model_words(model)
    return next((word for level in TIER_LEVELS for word in level & words), None)


def outranks(requested, caller):
    requested_rank = tier_rank(requested)
    caller_rank = tier_rank(caller)
    if requested_rank is None or caller_rank is None:
        return False
    return requested_rank > caller_rank
