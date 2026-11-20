"""@brief The passage from the village to the town: the town hall site
(docs/DESIGN.md, "The town hall site", 2026-11-20).

The village palace is rebuilt as the town hall on its own hexes: no place to
find. Opening the site needs the conditions below and the [town_hall] cost;
the builders are taken off the work for the whole site, after the guards
(GameState.free_adults). A strike month does not count. When the works end
the realm is a town (event "era_reached", public).

Rare resources in the recipe come later (stage 2); until then the recipe is
wood, stone and gold.
"""

from engine.config import Config
from engine.state import Event, GameState

VILLAGE, TOWN = "village", "town"
NO_WORK_UNREST = ("strike", "revolt")  # the site needs an orderly realm


def _month_of(turn: int) -> int:
    return (turn - 1) % 12 + 1


def last_winter_start(turn: int) -> int:
    """@brief The turn of the October that opened the last winter already
    ended (October to March) before this turn. It may be zero or negative:
    the game opens in January, inside its first winter.
    Example: turn 16 (April of year 2) -> 10 (October of year 1)."""
    months_since_march = (_month_of(turn) - 3) % 12 or 12
    return turn - months_since_march - 5


def no_hunger_since_last_winter(state: GameState) -> bool:
    """@brief No famine from the start of the last finished winter to now.
    The design asks "a winter without hunger"; a famine after that winter
    counts too, since only the last famine's month is kept (and a realm
    starving in summer is not ready for a site of six months).
    False before the first winter has ended (turns 1-3)."""
    if state.turn <= 3:
        return False
    never = state.last_famine_turn == 0  # turns start at 1
    return never or state.last_famine_turn < last_winter_start(state.turn)


def has_active_market(state: GameState) -> bool:
    return any(b.kind == "market" and b.turns_left == 0 for b in state.buildings)


def town_hall_conditions(state: GameState, config: Config) -> list[tuple[str, str, bool]]:
    """@brief The conditions to open the site (cost and builders apart):
    (stable key, English text, met). The page words the keys in Italian
    (server/ui/labels.py). Empty when the game has no town hall."""
    if config.town_hall is None:
        return []
    return [
        ("population", f"population {state.population()} of {config.town_hall.min_population}",
         state.population() >= config.town_hall.min_population),
        ("market", "a finished market", has_active_market(state)),
        ("hunger", "no hunger since the last winter began", no_hunger_since_last_winter(state)),
        ("unrest", "no strike or revolt", state.unrest not in NO_WORK_UNREST),
    ]


def town_hall_missing(state: GameState, config: Config) -> list[str]:
    """@brief The conditions not met yet (empty: the site may open, cost apart)."""
    return [text for _, text, met in town_hall_conditions(state, config) if not met]


def advance_town_hall(state: GameState, events: list[Event]) -> None:
    """@brief One month of works on the site, unless the people strike.
    At the end the realm is a town and the builders go back to work."""
    if state.town_hall_site == 0 or state.unrest in NO_WORK_UNREST:
        return
    state.town_hall_site -= 1
    if state.town_hall_site == 0:
        state.era = TOWN
        state.builders = 0
        events.append(Event("era_reached", {"era": TOWN}))
