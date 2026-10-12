from typing import NamedTuple

from rule_sections import RuleSection

ALL_SECTIONS = frozenset(RuleSection)
CODING_SECTIONS = frozenset(
    {
        RuleSection.COMMUNICATION,
        RuleSection.CLARITY,
        RuleSection.NEVER_SOUND_LIKE_AN_AI,
        RuleSection.CODE,
        RuleSection.ENGINEERING,
        RuleSection.USER_INTERFACE,
        RuleSection.GIT,
        RuleSection.YOUR_BEHAVIOUR,
    }
)


class Agent(NamedTuple):
    name: str
    rule_sections: frozenset[RuleSection]


AGENTS = (
    Agent("misticos:coder", CODING_SECTIONS),
    Agent("misticos:engineer", CODING_SECTIONS),
    Agent("misticos:reviewer", CODING_SECTIONS | {RuleSection.REVIEWS}),
    Agent("misticos:scout", frozenset()),
    Agent("misticos:watcher", frozenset()),
    Agent(
        "misticos:witness",
        frozenset(
            {
                RuleSection.CLARITY,
                RuleSection.NEVER_SOUND_LIKE_AN_AI,
                RuleSection.USER_INTERFACE,
            }
        ),
    ),
)
AGENTS_BY_NAME = {agent.name: agent for agent in AGENTS}


def rule_sections_for(agent_type):
    agent = AGENTS_BY_NAME.get(agent_type)
    return agent.rule_sections if agent else ALL_SECTIONS
