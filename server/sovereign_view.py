"""@brief What the sovereign may know of their own realm.

A sovereign can count granaries, coffers, people and buildings, but knows
the people's mood only through the Voice of the square and the council
(approved design: no mood number, no summary word). Every sovereign-facing
page and endpoint gets the state through sovereign_state(), so a hidden
field cannot leak by mistake; the admin view uses the full state instead.
"""

from dataclasses import asdict

from engine.state import GameState

HIDDEN_FROM_SOVEREIGN = (
    "mood",
    "low_mood_turns",
    "birth_acc",
    "death_acc",
    "aging_acc",
    "rng_seed",
    "feast_gold_this_turn",
    # The land levels are a secret the council finds out from its production
    # (docs/DESIGN.md, "Land levels"); found leaking through GET /state, 2026-11-09.
    "land_levels",
)


def sovereign_state(state: GameState) -> dict:
    """@brief Plain dict of the state without the hidden fields."""
    visible = asdict(state)
    for field in HIDDEN_FROM_SOVEREIGN:
        visible.pop(field)
    # Classes born from buildings (village block A): their unrest is public,
    # their mood, low-mood months and trade memory are not.
    visible["classes"] = {name: {"unrest": cls.unrest} for name, cls in state.classes.items()}
    return visible
