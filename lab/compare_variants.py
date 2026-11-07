"""@brief Compare balance variants over two years of play.

Usage: docker compose run --rm tests python lab/compare_variants.py

Each variant is the base config with a few values replaced. Each one is
played twice: with no orders ("passive") and with a simple scripted
player ("active") that builds farms and houses when needed and puts idle
adults to work. Numbers to read: food at the end of each winter and
year, idle adults, unspent resources, mood.
"""

from dataclasses import replace

from engine import load_config, new_game, parse_order, resolve_turn
from engine.turn import food_needed

BASE = load_config()


def with_changes(config, start=None, economy=None, buildings=None):
    """@brief Copy of config with some fields replaced (dict per section)."""
    new_buildings = dict(config.buildings)
    for kind, fields in (buildings or {}).items():
        new_buildings[kind] = replace(config.buildings[kind], **fields)
    return replace(
        config,
        start=replace(config.start, **(start or {})),
        economy=replace(config.economy, **(economy or {})),
        buildings=new_buildings,
    )


VARIANTS = {
    "base": BASE,
    "food 1600": with_changes(BASE, start={"food": 1600}),
    "farm 14 jobs": with_changes(BASE, buildings={"farm": {"jobs": 14}}),
    "farm 14 jobs + food 1800": with_changes(
        BASE, start={"food": 1800}, buildings={"farm": {"jobs": 14}}
    ),
    "farm 14 + low wood/stone": with_changes(
        BASE,
        buildings={
            "farm": {"jobs": 14},
            "sawmill": {"output_per_worker": 4},
            "quarry": {"output_per_worker": 3},
        },
    ),
}


def _order(raw):
    order, code, message = parse_order(raw)
    assert code is None, message
    return order


def active_player(state, config):
    """@brief A plain, sensible player: no clever tricks on purpose."""
    orders = []
    reserve_months = state.food / max(1, food_needed(state, config))
    housing = sum(config.buildings[b.kind].housing for b in state.buildings)
    farms_building = any(b.kind == "farm" and b.turns_left > 0 for b in state.buildings)
    if reserve_months < 3 and not farms_building:
        orders.append(_order({"action": "build", "building": "farm"}))
    if state.population() + 5 >= housing:
        orders.append(_order({"action": "build", "building": "house"}))
    farm_jobs = sum(
        config.buildings["farm"].jobs
        for b in state.buildings
        if b.kind == "farm" and b.turns_left == 0
    )
    food_workers = min(state.adults, farm_jobs)
    other = state.adults - food_workers
    orders.append(
        _order(
            {
                "action": "assign_workers",
                "food": food_workers,
                "wood": other // 2,
                "stone": other - other // 2,
            }
        )
    )
    if state.mood < 420 and state.gold >= 150:
        orders.append(_order({"action": "hold_feast", "gold": 150}))
    return orders


def play(config, player, turns=24):
    state = new_game(config, seed=1)
    rows = []
    for _ in range(turns):
        orders = player(state, config) if player else []
        state = resolve_turn(state, orders, config).state
        rows.append(state)
        if state.game_over:
            break
    return rows


def summary(rows):
    def food_at(turn):
        return rows[turn - 1].food if len(rows) >= turn else "-"

    last = rows[-1]
    idle = last.adults - last.workers.total()
    return (
        f"winter1 {food_at(3):>5} | year1 {food_at(12):>5} | winter2 {food_at(15):>5} "
        f"| year2 {food_at(24):>5} | pop {last.population():>3} | idle {idle:>2} "
        f"| wood {last.wood:>4} stone {last.stone:>4} gold {last.gold:>4} "
        f"| mood {last.mood} {last.unrest} {last.game_over or ''}"
    )


if __name__ == "__main__":
    for name, config in VARIANTS.items():
        print(f"{name}")
        print(f"  passive: {summary(play(config, None))}")
        print(f"  active:  {summary(play(config, active_player))}")
