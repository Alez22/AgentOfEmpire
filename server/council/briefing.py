"""@brief Role briefings: compact text with every number computed by the engine.

The models read words and numbers here; they never compute anything.
Pure functions: no database access (the meeting module passes the data in).
"""

import json
from collections import Counter

from engine.config import Config
from engine.state import GameState
from engine.turn import (
    expected_output,
    food_needed,
    housing_capacity,
    jobs_in_sector,
    monthly_tax_income,
    monthly_upkeep,
    season_of,
)
from server.council.llm import PROPOSALS_MARKER

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def months_until_winter(turn: int) -> int:
    """@brief 0 while it is winter (January-March), else months to January."""
    month_index = (turn - 1) % 12
    return 0 if month_index < 3 else 12 - month_index


def _reserve_months_text(state: GameState, config: Config) -> str:
    needed = food_needed(state, config)
    if needed == 0:
        return "unlimited"
    tenths = state.food * 10 // needed
    return f"{tenths // 10}.{tenths % 10}"


def header_lines(state: GameState) -> list[str]:
    month = MONTHS[(state.turn - 1) % 12]
    winter = months_until_winter(state.turn)
    winter_text = "it is winter now" if winter == 0 else f"winter in {winter} months"
    return [f"# Briefing, turn {state.turn}: {month}, {season_of(state.turn)}; {winter_text}"]


def _farm_season_pct(state: GameState, config: Config) -> int:
    economy = config.economy
    return {"winter": economy.farm_winter_pct, "spring": economy.farm_spring_pct,
            "summer": economy.farm_summer_pct, "autumn": economy.farm_autumn_pct}[season_of(state.turn)]


def food_outlook_line(state: GameState, config: Config) -> str:
    """@brief This month's harvest and where the store would end, if nothing changes."""
    harvest = expected_output(state, config)["food"]
    needed = food_needed(state, config)
    left = max(0, state.food + harvest - needed)
    left -= left * config.economy.food_spoilage_pct // 100
    trend = "it grows" if left > state.food else "it shrinks" if left < state.food else "it holds"
    return (f"- Harvest expected this month if nothing changes: {harvest} food "
            f"({season_of(state.turn)}: farms yield {_farm_season_pct(state, config)}%). "
            f"After eating and rot the store would go from {state.food} to about {left}: {trend}.")


def treasury_lines(state: GameState, config: Config) -> list[str]:
    return [
        "## Treasury and people",
        f"- Gold: {state.gold}. Tax income per month at {state.tax_rate}%: "
        f"{monthly_tax_income(state, config)}. Building upkeep per month: {monthly_upkeep(state, config)}.",
        f"- Food in store: {state.food}. Eaten per month at '{state.ration}' ration: "
        f"{food_needed(state, config)}. Without any harvest it would last about "
        f"{_reserve_months_text(state, config)} months. "
        f"Stored food rots by {config.economy.food_spoilage_pct}% per month.",
        food_outlook_line(state, config),
        f"- Tax rate: {state.tax_rate}% (maximum {config.economy.max_tax_rate}%). Ration: {state.ration}.",
        # No mood number, threshold or months below it: the council, like the
        # sovereign, knows the people only from the square (see square_lines).
        # Protests and strikes are public facts, so the unrest level stays.
        f"- Unrest: {state.unrest} (calm, protests, strike, revolt).",
        f"- Population: {state.children} children, {state.adults} adults, {state.elders} elders.",
    ]


def _vacant(state: GameState, config: Config, sector: str) -> int:
    return max(0, jobs_in_sector(state, config, sector) - getattr(state.workers, sector))


def works_lines(state: GameState, config: Config) -> list[str]:
    active = Counter(b.kind for b in state.buildings if b.turns_left == 0)
    building = [f"{b.kind} ({b.turns_left} turns left)" for b in state.buildings if b.turns_left > 0]
    idle = state.adults - state.workers.total()
    output = expected_output(state, config)
    costs = [
        f"{kind}: wood {spec.wood}, stone {spec.stone}, gold {spec.gold}, {spec.build_turns} turns"
        for kind, spec in config.buildings.items()
    ]
    return [
        "## Works and workers",
        f"- Wood: {state.wood}. Stone: {state.stone}. Gold: {state.gold}.",
        "- Buildings in use: " + ", ".join(f"{count} {kind}" for kind, count in sorted(active.items())) + ".",
        "- Under construction: " + (", ".join(building) if building else "nothing") + ".",
        f"- Free tiles for new buildings: {state.free_tiles}.",
        f"- Workers (assigned/jobs): food {state.workers.food}/{jobs_in_sector(state, config, 'food')}, "
        f"wood {state.workers.wood}/{jobs_in_sector(state, config, 'wood')}, "
        f"stone {state.workers.stone}/{jobs_in_sector(state, config, 'stone')}. "
        f"Adults: {state.adults}, without work: {idle}. Workers beyond the jobs produce nothing.",
        f"- Jobs without workers: food {_vacant(state, config, 'food')}, wood {_vacant(state, config, 'wood')}, "
        f"stone {_vacant(state, config, 'stone')}. A new building adds jobs, not workers: "
        "it produces nothing unless adults are free to fill it.",
        f"- Expected this month if nothing changes: food +{output['food']}, wood +{output['wood']}, "
        f"stone +{output['stone']}.",
        f"- Housing: {state.population()} people, {housing_capacity(state, config)} places.",
        "- Building costs: " + "; ".join(costs) + ".",
    ]


def events_lines(events: list[dict]) -> list[str]:
    """@brief Events of the previous turn already filtered by row-level security."""
    if not events:
        return ["## Last month", "- Nothing worth reporting."]
    return ["## Last month"] + [
        f"- {event['kind']}: {json.dumps(event['data'], ensure_ascii=False)}" for event in events
    ]


def history_lines(history: list[str]) -> list[str]:
    """@brief Past proposals with what followed (entries may span several lines)."""
    if not history:
        return []
    return ["## Your recent proposals and what followed"] + [f"- {entry}" for entry in history]


def audience_lines(dialogue: list[str]) -> list[str]:
    """@brief This actor's own private audiences; secret from everyone else."""
    if not dialogue:
        return []
    return ["## Your private audiences with the sovereign"] + [f"- {line}" for line in dialogue]


def square_lines(voices: list[tuple[int, str]]) -> list[str]:
    """@brief What the Voice of the square said in recent turns, oldest first.
    This is the council's only window on the people's mood.
    @param voices (turn, text) pairs; the Voice speaks at the start of a turn.
    """
    if not voices:
        return []
    lines = ["## What they say in the square"]
    for turn, text in voices:
        lines.append(f"- At the start of {MONTHS[(turn - 1) % 12]} (turn {turn}): {text}")
    return lines


def audience_fact_lines(facts: list[str]) -> list[str]:
    if not facts:
        return []
    return ["## Private audiences this month"] + [f"- {fact}" for fact in facts]


def lessons_lines(lessons: list[str]) -> list[str]:
    """@brief The minister's own lessons; secret from the sovereign."""
    if not lessons:
        return []
    return ["## What you have learned so far"] + [f"- {lesson}" for lesson in lessons]


def directive_lines(directives: list[str]) -> list[str]:
    if not directives:
        return []
    return ["## Directives of the sovereign this turn"] + [f"- {text}" for text in directives]


def minister_briefing(
    role: str, state: GameState, config: Config, events: list[dict],
    history: list[str], directives: list[str], lessons: list[str],
    audiences: list[str] = (), audience_facts: list[str] = (), square_voices: list = (),
) -> str:
    """@brief Full briefing of a minister; each role sees only its own section.
    Lessons come first: they are the lens through which the numbers are read.
    """
    section = treasury_lines(state, config) if role == "treasurer" else works_lines(state, config)
    lines = (header_lines(state) + lessons_lines(lessons) + section + events_lines(events)
             + square_lines(list(square_voices))
             + history_lines(history) + audience_lines(list(audiences))
             + audience_fact_lines(list(audience_facts)) + directive_lines(directives))
    return "\n".join(lines)


def chancellor_briefing(
    state: GameState, config: Config, events: list[dict], directives: list[str],
    reports: dict[str, str], proposals: list[dict], check_lines: list[str], lessons: list[str],
    audiences: list[str] = (), audience_facts: list[str] = (), square_voices: list = (),
) -> str:
    """@brief The Chancellor sees both sections, the reports, the proposals
    (also as one JSON line, easy to quote back) and the scribes' cost check.
    """
    lines = (header_lines(state) + lessons_lines(lessons)
             + treasury_lines(state, config) + works_lines(state, config))
    lines += (events_lines(events) + square_lines(list(square_voices)) + audience_lines(list(audiences))
              + audience_fact_lines(list(audience_facts)) + directive_lines(directives))
    lines.append("## Reports of the ministers")
    lines += [f"- {role}: {text}" for role, text in reports.items()]
    lines.append("## Cost check of all proposals together, in this order")
    lines += [f"- {line}" for line in check_lines] or ["- No proposals."]
    lines.append(PROPOSALS_MARKER + json.dumps(proposals, ensure_ascii=False))
    return "\n".join(lines)
