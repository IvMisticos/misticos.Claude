---
name: research
description: Research a topic on the web with many misticos:scout agents, after a short interview with the user, and write a compact report from per-angle notes. Use when the user asks to research or investigate a topic, compare options, review literature, or collect what other people found or lived through, or asks for deep research.
---

Research in five steps: interview, split, scout, fill gaps, report.

## 1. Interview

Before you search, ask all your questions in one message, and say that the user can skip any of them. Write the questions for this topic, and ask only what the request leaves open and what would change the angles, the sources, or the report:

- what the user wants to learn, and what they will do with it,
- what is in and out of scope, such as a period, a place, a group, or a language,
- the form of the report, who reads it, and its language,
- sources to trust or avoid,
- many options in brief or a few in depth, and how much to cite.

Where the user doesn't choose, research many options in brief, search in any language, avoid content farms and AI-written pages, cite only where a number or a quote carries a conclusion, and write the report in the user's language.

## 2. Split

Split the topic into angles. An angle is one question that one scout answers from public sources, within about 100k tokens of context. Split an angle that needs more. Make at least 20 angles, and as many more as the goal needs, with no overlap.

Take the angles from the goal, and mix the kinds of evidence: data, first-hand accounts, experts and primary sources, leading examples, how things work, opposing views, and what failed for others. A business topic also needs the market, money, and law.

Give each angle a short kebab-case name. Send the user the list, and start without waiting for a reply.

## 3. Scout

Run `scout.js` from this skill's folder with the Workflow tool, through `scriptPath`. This skill is the user's consent to that Workflow, at one scout per angle. Pass `args`:

- `goal`: what the user wants to learn, and what they will do with it,
- `scope`: what is in and out of scope,
- `trust`: a list of sources to prefer,
- `avoid`: a list of sources to avoid,
- `angles`: a list of `{ name, question, known }`, where `known` lists the URLs an earlier run of the angle already found.

All agents in a turn share one limit on web searches. The script stops starting scouts after the first one reaches it, and returns `findingsByAngle` and `unfinishedAngles`. An angle that reached the limit is in both, with the findings it got before it stopped. The limit resets each turn. If any angle is unfinished, save the notes, tell the user which angles are left, ask them to reply so you can continue, and end your turn. In the next turn, run the unfinished angles with the URLs from their notes as `known`, and add the new findings to those notes. Go on to step 4 only when no angle is unfinished. Never write a note without findings.

Save the findings of each scout in `<folder>/<topic>/notes/<angle>.md`. The folder is one the user names, or the working directory. Keep every number, quote, and URL, and remove repeats.

## 4. Fill gaps

Read the notes. List what is missing, what is weak, and where two notes disagree. Run new scouts for these gaps in the same way. Repeat until a round adds nothing that changes the report.

## 5. Report

Write the report in the form and language from the interview, or in `<folder>/<topic>/report.md` if the user didn't choose a form. Keep every fact that matters for the goal, and nothing else. Start with the answers to the goal, then the evidence by angle, then the open questions. Use tables for comparisons. For projections, name the source note of each assumption, and show a low, a middle, and a high case.

Start your reply with the three to five findings that matter most for the goal.
