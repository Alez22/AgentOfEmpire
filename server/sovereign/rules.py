"""@brief The fixed rules of the automatic sovereign, from game 24
(docs/DESIGN.md, "Automatic sovereign, first version"; docs/game24_notes.md).

Pure functions: state, config and market in, decisions with their reasons
(Italian, shown to the player) out. No database, no model.

Rule names follow the draft of game 24: R1 petitions, R2 winter food,
R3 no claims in winter, R4b useless purchases, R5 sell when gold is short,
R6 tax cuts, R7 buy what runs short, R8 empty buildings, R9 feasts.
"""

import copy
from dataclasses import dataclass

from engine import parse_order
from engine.config import Config
from engine.market import MarketState, buy_price, check_month_plan, sell_price, state_after_trades, stock
from engine.orders import Order, TradeOrder
from engine.state import GameState
from engine.turn import (firewood_needed, food_needed, monthly_tax_income, monthly_upkeep, resolve_turn,
                         season_of, stone_upkeep)
from server.ui import labels

FOOD_WATCH_MONTHS = (10, 11, 12, 1, 2, 3)  # October to March: the granary must reach spring
LAST_WINTER_MONTH = 3
BUY_COVER_MONTHS = 3  # R7: buy below this many months of need
USELESS_BUY_MONTHS = 4  # R4b: a purchase is useless above this many months of need
SELL_KEEP_MONTHS = 6  # R5: wood and stone kept before selling
SELL_KEEP_LOTS = 2  # R5: and this many lots more
SELL_FOOD_KEEP_MONTHS = 3  # R5: months of eating kept before selling food
GOLD_SHORT_MONTHS = 3  # R5: gold is short below this many months of costs
MAX_SELL_LOTS = 4


@dataclass
class Item:
    """@brief One plan item: its position, the parsed order and the check verdict."""
    index: int
    order: Order
    raw: dict
    accepted: bool


@dataclass
class Month:
    """@brief What the sovereign knows when it decides."""
    state: GameState
    config: Config
    market: MarketState | None
    realm_key: str


def month_of(turn: int) -> int:
    return (turn - 1) % 12 + 1


def plan_items(payload: dict) -> list[Item]:
    """@brief The Chancellor's plan (summary payload) as items."""
    verdicts = payload["check"]["verdicts"]
    return [Item(index, parse_order(item["order"])[0], item["order"], verdict["accepted"])
            for index, (item, verdict) in enumerate(zip(payload["plan"], verdicts))]


def costs(state: GameState, config: Config) -> int:
    """@brief Gold the realm owes every month: building upkeep and salaries."""
    return monthly_upkeep(state, config) + state.council_salary


def need_ahead(state: GameState, config: Config, good: str, months: int) -> int:
    """@brief Wood (firewood) or stone (upkeep) the realm needs in the next
    months, this one included."""
    if good == "stone":
        return stone_upkeep(state, config) * months
    later = copy.copy(state)
    total = 0
    for ahead in range(months):
        later.turn = state.turn + ahead
        total += firewood_needed(later, config)
    return total


def _famine(result) -> bool:
    return any(e.kind in ("famine", "game_over") for e in result.events)


def food_lasts(month: Month, orders: list[Order]) -> bool:
    """@brief The winter check: the month runs on a copy (trades filled in
    full, then the plan), then month after month with no orders.
    October to March: no famine until the end of March. Other months: no
    famine this month and one month of eating left."""
    trades = [o for o in orders if isinstance(o, TradeOrder)]
    others = [o for o in orders if not isinstance(o, TradeOrder)]
    trial = state_after_trades(month.state, trades, month.market, month.config, month.realm_key)
    result = resolve_turn(trial, others, month.config)
    if _famine(result):
        return False
    now = month_of(month.state.turn)
    if now not in FOOD_WATCH_MONTHS:
        return result.state.food >= food_needed(result.state, month.config)
    months_left = (LAST_WINTER_MONTH - now) % 12
    later = result.state
    for _ in range(months_left):
        if later.game_over:
            return False
        result = resolve_turn(later, [], month.config)
        if _famine(result):
            return False
        later = result.state
    return True


def _remaining(month: Month, orders: list[Order]) -> dict[str, int]:
    return check_month_plan(month.state, orders, month.market, month.config, month.realm_key).remaining


def _has_on_sale(month: Month, good: str) -> bool:
    return any(c.seller == month.realm_key for c in month.market.goods[good].queue)


def _trades_good(items: list[Item], good: str, side: str) -> bool:
    return any(isinstance(i.order, TradeOrder) and i.order.good == good and i.order.side == side for i in items)


# ----------------------------------------------------------- directives

def _buy_directive(month: Month, items: list[Item], left: dict[str, int]) -> tuple[str, str] | None:
    """@brief R7: wood or stone running short and on sale at the market."""
    lot = month.config.market.lot_units
    for good in ("wood", "stone"):
        need = need_ahead(month.state, month.config, good, BUY_COVER_MONTHS)
        if left[good] >= need or _trades_good(items, good, "buy") or _has_on_sale(month, good):
            continue
        if stock(month.market.goods[good]) == 0:
            continue
        lots = min(-(-(need - left[good]) // lot), left["gold"] // buy_price(month.market, month.config, good))
        if lots < 1:
            continue
        what = labels.lots_of(lots, good)
        return (f"Tesoriere, compra al mercato {what}.",
                f"Direttiva: comprare {what}: {labels.GOODS_IT[good]} per meno di {BUY_COVER_MONTHS} mesi "
                f"di bisogno ({left[good]} contro {need}) (R7).")
    return None


def _food_lots_to_sell(month: Month, orders: list[Order], left_food: int) -> int:
    lot = month.config.market.lot_units
    keep = SELL_FOOD_KEEP_MONTHS * food_needed(month.state, month.config)
    for lots in range(min(MAX_SELL_LOTS, (left_food - keep) // lot), 0, -1):
        sale = parse_order({"action": "trade", "good": "food", "side": "sell", "lots": lots})[0]
        if food_lasts(month, orders + [sale]):
            return lots
    return 0


def _sell_directive(month: Month, items: list[Item], left: dict[str, int]) -> tuple[str, str] | None:
    """@brief R5: gold short and a good above its needs: sell the one that
    brings the most gold."""
    monthly_costs = costs(month.state, month.config)
    if left["gold"] >= GOLD_SHORT_MONTHS * monthly_costs:
        return None
    lot = month.config.market.lot_units
    orders = [i.order for i in items]
    best = None
    for good in ("food", "wood", "stone"):
        if _trades_good(items, good, "sell"):
            continue
        if good == "food":
            lots = _food_lots_to_sell(month, orders, left["food"])
        else:
            keep = need_ahead(month.state, month.config, good, SELL_KEEP_MONTHS) + SELL_KEEP_LOTS * lot
            lots = min(MAX_SELL_LOTS, max(0, (left[good] - keep) // lot))
        gold = lots * sell_price(month.market, month.config, good)
        if lots >= 1 and (best is None or gold > best[2]):
            best = (good, lots, gold)
    if best is None:
        return None
    good, lots, _ = best
    what = labels.lots_of(lots, good)
    return (f"Tesoriere, vendi al mercato {what}.",
            f"Direttiva: vendere {what}: l'oro ({left['gold']}) copre meno di {GOLD_SHORT_MONTHS} mesi di "
            f"spese ({monthly_costs} al mese) (R5).")


def directive(month: Month, items: list[Item]) -> tuple[str, str] | None:
    """@brief At most one directive: (text for the council, reason) or None.
    R7 before R5: a need first."""
    if month.market is None or month.config.market is None:
        return None
    accepted = [i for i in items if i.accepted]
    left = _remaining(month, [i.order for i in accepted])
    return _buy_directive(month, accepted, left) or _sell_directive(month, accepted, left)


# ------------------------------------------------------------ petition

def petition_answer(month: Month, petition: dict, items: list[Item]) -> tuple[str, str]:
    """@brief R1: ("granted" or "refused", reason). Checked with the petition
    first, as the turn runs it."""
    order = parse_order(petition)[0]
    label = labels.order_label(petition)
    plan = [i.order for i in items if i.accepted and i.raw.get("action") != petition.get("action")]
    monthly_costs = costs(month.state, month.config)
    if petition["action"] == "set_tax":
        income = month.state.adults * petition["rate"] // month.config.economy.tax_divisor
        if income >= monthly_costs:
            return "granted", f"Supplica esaudita ({label}): le entrate ({income}) coprono le spese ({monthly_costs}) (R1)."
        return "refused", f"Supplica respinta ({label}): le entrate ({income}) non coprono le spese ({monthly_costs}) (R1)."
    if petition["action"] == "set_ration":
        if food_lasts(month, [order] + plan):
            return "granted", f"Supplica esaudita ({label}): il cibo basta (R1)."
        return "refused", f"Supplica respinta ({label}): il cibo non arriverebbe alla primavera (R1)."
    if petition["action"] == "hold_feast":
        gold_left = _remaining(month, [order] + plan)["gold"]
        if gold_left >= monthly_costs:
            return "granted", f"Supplica esaudita ({label}): resta oro per le spese del mese (R1, R9)."
        return "refused", f"Supplica respinta ({label}): resterebbero {gold_left} oro, meno delle spese del mese (R1, R9)."
    return "refused", f"Supplica respinta ({label}): nessuna regola la prevede (R1)."


# ---------------------------------------------------------- exclusions

def _farmers_off(month: Month, item: Item) -> str:
    if item.raw.get("action") != "assign_workers" or month_of(month.state.turn) not in FOOD_WATCH_MONTHS:
        return ""
    taken = month.state.workers.food - item.order.food
    if taken <= 0:
        return ""
    return f"toglie {taken} contadini ai campi tra l'autunno e l'inverno (R2)"


def _claim_in_winter(month: Month, item: Item) -> str:
    if item.raw.get("action") == "claim_tiles" and season_of(month.state.turn) == "winter":
        return "niente nuove terre d'inverno: l'oro serve al mercato (R3)"
    return ""


def _tax_cut(month: Month, item: Item) -> str:
    if item.raw.get("action") != "set_tax" or item.order.rate >= month.state.tax_rate:
        return ""
    income = month.state.adults * item.order.rate // month.config.economy.tax_divisor
    monthly_costs = costs(month.state, month.config)
    if income >= monthly_costs:
        return ""
    return f"le entrate ({income}) scenderebbero sotto le spese ({monthly_costs}) (R6)"


def _empty_places(month: Month, kind: str) -> tuple[int, int]:
    """@brief (empty jobs or house places, those of one new building), sites
    under construction included."""
    config, state = month.config, month.state
    spec = config.buildings[kind]
    if kind == "house":
        places = sum(config.buildings[b.kind].housing for b in state.buildings)
        return places - state.population(), spec.housing
    jobs = sum(config.buildings[b.kind].jobs for b in state.buildings if config.buildings[b.kind].sector == spec.sector)
    return jobs - getattr(state.workers, spec.sector), spec.jobs


def _empty_building(month: Month, item: Item) -> str:
    if item.raw.get("action") != "build":
        return ""
    empty, one_building = _empty_places(month, item.order.building)
    if empty * 2 < one_building:
        return ""
    what = "posti letto" if item.order.building == "house" else "posti di lavoro"
    return f"ci sono già {empty} {what} vuoti (R8)"


def _useless_buy(month: Month, item: Item, others: list[Order]) -> str:
    order = item.order
    if not isinstance(order, TradeOrder) or order.side != "buy" or order.good == "food":
        return ""
    need = need_ahead(month.state, month.config, order.good, USELESS_BUY_MONTHS)
    left = _remaining(month, others)[order.good]
    if left < need:
        return ""
    return f"{labels.GOODS_IT[order.good]} basta già per {USELESS_BUY_MONTHS} mesi ({left} contro {need}) (R4b)"


def _costly_feast(month: Month, item: Item, kept: list[Order]) -> str:
    if item.raw.get("action") != "hold_feast":
        return ""
    gold_left = _remaining(month, kept)["gold"]
    monthly_costs = costs(month.state, month.config)
    if gold_left >= monthly_costs:
        return ""
    return f"resterebbero {gold_left} oro, meno delle spese del mese ({monthly_costs}) (R9)"


def exclusions(month: Month, items: list[Item], granted: dict | None) -> list[tuple[int, str]]:
    """@brief Plan items to leave out, with their reasons: (index, reason).
    Only items the engine check accepted; a granted petition runs first.
    @param granted The granted petition's order, or None."""
    first = [parse_order(granted)[0]] if granted else []
    kept = [i for i in items if i.accepted and not (granted and i.raw.get("action") == granted.get("action"))]
    excluded: list[tuple[int, str]] = []

    def orders_without(item: Item) -> list[Order]:
        return first + [i.order for i in kept if i is not item]

    for item in list(kept):
        reason = (_farmers_off(month, item) or _claim_in_winter(month, item) or _tax_cut(month, item)
                  or _empty_building(month, item) or _useless_buy(month, item, orders_without(item)))
        if reason:
            excluded.append((item.index, reason))
            kept.remove(item)
    for item in list(kept):
        reason = _costly_feast(month, item, first + [i.order for i in kept])
        if reason:
            excluded.append((item.index, reason))
            kept.remove(item)
    # R2: the winter check, the latest items first (they weigh least in the plan).
    for item in reversed(list(kept)):
        if food_lasts(month, first + [i.order for i in kept]):
            break
        if food_lasts(month, orders_without(item)):
            excluded.append((item.index, "senza questo ordine il cibo arriva alla primavera, con questo no (R2)"))
            kept.remove(item)
    return sorted(excluded)
