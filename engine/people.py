"""@brief What the people decide each month, and the limits of that choice.

The decision itself is taken outside the engine (a cheap model, or fixed
rules when the model is silent) and stored with the turn, like an order:
the engine only applies it, so a replay stays exact.

The limits depend on the mood band: a content people cannot drag its feet,
a discontented one cannot work with zeal. Whoever decides only chooses
inside these ranges; clamp_choice() enforces them.
"""

from dataclasses import dataclass

from engine.config import Config, PeopleConfig
from engine.state import GameState

PETITION_ANSWERS = ("granted", "refused")


@dataclass(frozen=True)
class PeopleChoice:
    effort_pct: int = 0  # added to the yield of fields, sawmill and quarry
    birth_pct: int = 100  # multiplier of this month's births
    petition: str | None = None  # "granted" or "refused"; None = no petition


def mood_band(state: GameState, people: PeopleConfig) -> str:
    if state.mood > people.content_above:
        return "content"
    if state.mood < people.discontent_below:
        return "discontented"
    return "neutral"


def allowed_ranges(state: GameState, config: Config) -> dict[str, tuple[int, int]]:
    """@brief Inclusive (min, max) per behaviour for this month's mood band."""
    people = config.people
    band = mood_band(state, people)
    return {
        "effort_pct": tuple(getattr(people, f"effort_{band}")),
        "birth_pct": tuple(getattr(people, f"birth_{band}")),
    }


def clamp_choice(state: GameState, config: Config, effort_pct: int, birth_pct: int) -> tuple[int, int]:
    """@brief Bring a proposed choice inside the allowed ranges."""
    ranges = allowed_ranges(state, config)
    low, high = ranges["effort_pct"]
    effort = max(low, min(high, effort_pct))
    low, high = ranges["birth_pct"]
    births = max(low, min(high, birth_pct))
    return effort, births


def rule_choice(state: GameState, config: Config) -> tuple[int, int]:
    """@brief Fixed-rule fallback when the model does not answer: the middle
    of each range, rounded towards zero change."""
    ranges = allowed_ranges(state, config)
    effort = sum(ranges["effort_pct"]) // 2
    births = sum(ranges["birth_pct"]) // 2
    return effort, births
