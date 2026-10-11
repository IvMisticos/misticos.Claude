from enum import StrEnum


class AgentType(StrEnum):
    CODER = "misticos:coder"
    ENGINEER = "misticos:engineer"
    REVIEWER = "misticos:reviewer"
    SCOUT = "misticos:scout"
    WITNESS = "misticos:witness"
