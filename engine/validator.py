"""@brief Validate orders against the state and apply the accepted ones.

An order is all-or-nothing. Orders run in a fixed sequence (priority,
then submission order) and each accepted order consumes resources before
the next one is checked, so conflicts always resolve the same way.
"""

import copy
from dataclasses import dataclass

from engine.config import Config
from engine import territory
from engine.orders import (
    AssignWorkersOrder,
    BuildOrder,
    DemolishOrder,
    HoldFeastOrder,
    Order,
    SetRationOrder,
    SetTaxOrder,
    SetZonesOrder,
)
from engine.state import Building, GameState, Workers, Zone

# Orders that change the map run before the others of the same priority,
# so a build can use the new town plan and the tiles a demolition frees.
MAP_FIRST_ACTIONS = ("set_zones", "demolish")


@dataclass
class OrderResult:
    order: Order
    accepted: bool
    code: str | None = None  # rejection code, None when accepted
    message: str = ""


@dataclass
class PlanReport:
    results: list[OrderResult]
    spent: dict[str, int]  # resources consumed by the accepted orders
    remaining: dict[str, int]  # resources left after them


def _reject(order: Order, code: str, message: str) -> OrderResult:
    return OrderResult(order, False, code, message)


def _place_on_map(state: GameState, order: BuildOrder, config: Config) -> tuple[tuple[int, int] | None, OrderResult | None]:
    """@brief Where the building goes: the given tile (or one tile away),
    else the place nearest the square in the zone.
    @return ((x, y), None), or (None, rejection).
    """
    if order.zone is not None and not any(zone.name == order.zone for zone in state.zones):
        return None, _reject(order, "UNKNOWN_ZONE", f"no zone named '{order.zone}'")
    if (order.x is None) != (order.y is None):
        return None, _reject(order, "INVALID_PARAM", "give both x and y, or neither")
    if order.x is None:
        place = territory.find_place(state, config, order.building, order.zone)
        if place is None:
            where = f"zone '{order.zone}'" if order.zone else "any zone of its kind"
            return None, _reject(order, "NO_SPACE", f"no room for a {order.building} in {where}")
        return place, None
    error = territory.place_error(state, config, order.building, order.x, order.y, order.zone)
    if error is None:
        return (order.x, order.y), None
    place = territory.nudge(state, config, order.building, order.x, order.y, order.zone)
    if place is None:
        return None, _reject(order, *error)
    return place, None


def _apply_build(state: GameState, order: BuildOrder, config: Config) -> OrderResult:
    spec = config.buildings[order.building]
    place = None
    if state.has_map():
        place, rejection = _place_on_map(state, order, config)
        if rejection:
            return rejection
    elif state.free_tiles <= 0:
        return _reject(order, "NO_FREE_TILE", "no free tile for a new building")
    if state.wood < spec.wood or state.stone < spec.stone or state.gold < spec.gold:
        return _reject(
            order,
            "INSUFFICIENT_RESOURCES",
            f"{order.building} needs wood {spec.wood}, stone {spec.stone}, gold {spec.gold}",
        )
    state.wood -= spec.wood
    state.stone -= spec.stone
    state.gold -= spec.gold
    if place is None:  # no map: count the tile
        state.free_tiles -= 1
        state.buildings.append(Building(order.building, spec.build_turns))
        return OrderResult(order, True)
    state.buildings.append(Building(order.building, spec.build_turns, state.next_building_id, *place))
    state.next_building_id += 1
    return OrderResult(order, True)


def _apply_zones(state: GameState, order: SetZonesOrder, config: Config) -> OrderResult:
    if not state.has_map():
        return _reject(order, "NO_MAP", "this realm has no map")
    zones = [Zone(z.name.strip(), z.purpose, z.x1, z.y1, z.x2, z.y2) for z in order.zones]
    error = territory.zones_error(state, config, zones)
    if error:
        return _reject(order, "BAD_ZONES", error)
    state.zones = zones
    return OrderResult(order, True)


def _apply_demolish(state: GameState, order: DemolishOrder, config: Config) -> OrderResult:
    """@brief Pull a building down at once: its tiles are free for the
    orders after it, it produces nothing this month and costs no more upkeep.
    Its workers stay assigned; beyond the jobs they produce nothing, as today."""
    if not state.has_map():
        return _reject(order, "NO_MAP", "this realm has no map")
    building = next((b for b in state.buildings if b.id == order.building_id), None)
    if building is None:
        return _reject(order, "UNKNOWN_BUILDING", f"no building with id {order.building_id}")
    cost = config.map.demolish_gold
    if state.gold < cost:
        return _reject(order, "INSUFFICIENT_RESOURCES", f"demolition needs {cost} gold")
    spec = config.buildings[building.kind]
    state.gold -= cost
    state.wood += spec.wood * config.map.demolish_refund_pct // 100
    state.stone += spec.stone * config.map.demolish_refund_pct // 100
    state.buildings.remove(building)
    return OrderResult(order, True)


def _apply_assign(state: GameState, order: AssignWorkersOrder) -> OrderResult:
    requested = order.food + order.wood + order.stone
    if requested > state.adults:
        return _reject(
            order, "NOT_ENOUGH_WORKERS", f"{requested} requested, {state.adults} adults"
        )
    state.workers = Workers(order.food, order.wood, order.stone)
    return OrderResult(order, True)


def _apply_tax(state: GameState, order: SetTaxOrder, config: Config) -> OrderResult:
    if order.rate > config.economy.max_tax_rate:
        return _reject(
            order, "INVALID_PARAM", f"tax rate above {config.economy.max_tax_rate} %"
        )
    state.tax_rate = order.rate
    return OrderResult(order, True)


def _apply_feast(state: GameState, order: HoldFeastOrder) -> OrderResult:
    if state.gold < order.gold:
        return _reject(order, "INSUFFICIENT_RESOURCES", f"only {state.gold} gold")
    state.gold -= order.gold
    # The mood effect is applied in the mood step of the turn; the order
    # only records how much gold was spent this turn.
    state.feast_gold_this_turn += order.gold
    return OrderResult(order, True)


def _apply_ration(state: GameState, order: SetRationOrder) -> OrderResult:
    state.ration = order.ration
    return OrderResult(order, True)


def _apply_policy(
    state: GameState, order: SetTaxOrder | SetRationOrder, config: Config, policies_set: set[str]
) -> OrderResult:
    if order.action in policies_set:
        return _reject(order, "DUPLICATE_POLICY", f"{order.action} already set this turn")
    if isinstance(order, SetTaxOrder):
        result = _apply_tax(state, order, config)
    else:
        result = _apply_ration(state, order)
    if result.accepted:
        policies_set.add(order.action)
    return result


def _apply_one(
    state: GameState, order: Order, config: Config, policies_set: set[str]
) -> OrderResult:
    if isinstance(order, BuildOrder):
        return _apply_build(state, order, config)
    if isinstance(order, AssignWorkersOrder):
        return _apply_assign(state, order)
    if isinstance(order, HoldFeastOrder):
        return _apply_feast(state, order)
    if isinstance(order, SetZonesOrder):
        return _apply_zones(state, order, config)
    if isinstance(order, DemolishOrder):
        return _apply_demolish(state, order, config)
    return _apply_policy(state, order, config, policies_set)


def apply_orders(state: GameState, orders: list[Order], config: Config) -> list[OrderResult]:
    """@brief Validate and apply orders in place, in their fixed sequence.
    @param state State to modify (the caller passes a copy if needed).
    @param orders Orders already parsed by orders.parse_order.
    @param config Balance values.
    @return One result per order, in the sequence they were evaluated.
    """
    policies_set: set[str] = set()
    ordered = sorted(orders, key=lambda order: (order.priority, order.action not in MAP_FIRST_ACTIONS))
    return [_apply_one(state, order, config, policies_set) for order in ordered]


def check_plans(state: GameState, orders: list[Order], config: Config) -> PlanReport:
    """@brief Dry run of apply_orders: the conflict report for the Chancellor.
    @param state Current state; it is NOT modified.
    @param orders Candidate orders.
    @param config Balance values.
    @return Per-order verdicts, resources spent and resources remaining.
    """
    trial_state = copy.deepcopy(state)
    results = apply_orders(trial_state, orders, config)
    resources = ("food", "wood", "stone", "gold")
    spent = {name: getattr(state, name) - getattr(trial_state, name) for name in resources}
    remaining = {name: getattr(trial_state, name) for name in resources}
    return PlanReport(results, spent, remaining)
