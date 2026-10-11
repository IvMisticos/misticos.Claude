from typing import NamedTuple

from rule_sections import RuleSection

ALL_SECTIONS = frozenset(RuleSection)
ORCHESTRATOR_ONLY_SECTIONS = frozenset(
    {RuleSection.ISSUE_TRACKING, RuleSection.PULL_REQUESTS, RuleSection.DELEGATION}
)
WORKER_SECTIONS = ALL_SECTIONS - ORCHESTRATOR_ONLY_SECTIONS


class Agent(NamedTuple):
    name: str
    rule_sections: frozenset[RuleSection]


AGENTS = (
    Agent("misticos:coder", WORKER_SECTIONS - {RuleSection.REVIEWS}),
    Agent("misticos:engineer", WORKER_SECTIONS - {RuleSection.REVIEWS}),
    Agent("misticos:reviewer", WORKER_SECTIONS),
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
