"""@brief Validate orders against the state and apply the accepted ones.

An order is all-or-nothing. Orders run in a fixed sequence (priority,
then submission order) and each accepted order consumes resources before
the next one is checked, so conflicts always resolve the same way.
"""

import copy
from dataclasses import dataclass

from engine.config import Config
from engine.orders import (
    AssignWorkersOrder,
    BuildOrder,
    HoldFeastOrder,
    Order,
    SetRationOrder,
    SetTaxOrder,
)
from engine.state import Building, GameState, Workers


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


def _apply_build(state: GameState, order: BuildOrder, config: Config) -> OrderResult:
    spec = config.buildings[order.building]
    if state.free_tiles <= 0:
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
    state.free_tiles -= 1
    state.buildings.append(Building(order.building, spec.build_turns))
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
    return _apply_policy(state, order, config, policies_set)


def apply_orders(state: GameState, orders: list[Order], config: Config) -> list[OrderResult]:
    """@brief Validate and apply orders in place, in their fixed sequence.
    @param state State to modify (the caller passes a copy if needed).
    @param orders Orders already parsed by orders.parse_order.
    @param config Balance values.
    @return One result per order, in the sequence they were evaluated.
    """
    policies_set: set[str] = set()
    ordered = sorted(orders, key=lambda order: order.priority)
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
