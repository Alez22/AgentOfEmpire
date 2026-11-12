"""@brief The fixed rules of the automatic sovereign, from game 24
(docs/DESIGN.md, "Automatic sovereign, first version"; docs/game24_notes.md).

Pure functions: state, config and market in, decisions with their reasons
(Italian, shown to the player) out. No database, no model.

Rule names follow the draft of game 24: R1 petitions, R2 winter food,
R3 no claims in winter, R4b useless purchases, R5 sell when gold is short,
R6 tax cuts, R7 buy what runs short, R8 empty buildings, R9 feasts.
R2b (after game 27): no richer ration when the food does not last.
R10 (village block A, 2026-11-08): build the market, then staff it.
R10b (after game 40): no build of the council's at the cost of the firewood.
R11 (village block B+C, 2026-11-09): build the watchtower after the first raid.
R12 (seasonal sovereign, 2026-11-11): in an automatic month no law changes.
R13 (tools, 2026-11-12): no tools for empty places, nor with the firewood short.
"""

import copy
from dataclasses import dataclass

from engine import parse_order
from engine.config import Config
from engine.market import (MarketState, buy_price, check_month_plan, market_status, sell_price, state_after_trades,
                           stock, trade_capacity)
from engine.orders import AssignWorkersOrder, BuildOrder, ImproveOrder, Order, SetRationOrder, TradeOrder
from engine.state import GameState, Workers
from engine.territory import building_works
from engine.turn import (expected_output, firewood_needed, food_needed, monthly_tax_income, monthly_upkeep, resolve_turn,
                         season_of, stone_upkeep)
from server.ui import labels

FOOD_WATCH_MONTHS = (10, 11, 12, 1, 2, 3)  # October to March: the granary must reach spring
LAST_WINTER_MONTH = 3
BUY_COVER_MONTHS = 3  # R7: buy below this many months of need
USELESS_BUY_MONTHS = 4  # R4b: a stone purchase is useless above this many months of need
SELL_KEEP_MONTHS = 6  # R5: wood and stone kept before selling
SELL_KEEP_LOTS = 2  # R5: and this many lots more
GOLD_SHORT_MONTHS = 3  # R5: gold is short below this many months of costs
MAX_SELL_LOTS = 4
MERCHANTS_WANTED = 3  # R10: merchants asked for a new market (3 x 3 lots a month)
# R12: the laws only the sovereign changes in a seasonal game (the same four
# the reversal line tracks, server/ui/reversals.py).
LAWS = ("set_tax", "set_merchant_tax", "set_ration", "set_doors")
LOCKED_LAW = "è una legge della stagione, la cambia solo il sovrano (R12)"


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
    raided: bool = False  # the realm has suffered a raid (R11); the server reads its events


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


def wood_ahead(state: GameState, config: Config, months: int, workers: Workers) -> int:
    """@brief Wood the woodcutters cut in the next months, this one included,
    with these workers and no other order.
    Why: R13 weighed the firewood until spring against the stock alone, so in
    July it refused the iron axes to a sawmill with ten woodcutters (game 39:
    Dalmora, 49 wood against 260 of firewood to March)."""
    later = copy.deepcopy(state)
    later.workers = workers
    total = 0
    for ahead in range(months):
        later.turn = state.turn + ahead
        total += expected_output(later, config)["wood"]
    return total


def months_to_spring(turn: int) -> int:
    """@brief Months from this one to the end of the next March, both included.
    Why: R4b measured wood by the next 4 months, so from April to July it
    found no firewood ahead and refused any purchase (game 25: "12 contro 0")."""
    return (LAST_WINTER_MONTH - month_of(turn)) % 12 + 1


def _famine(result) -> bool:
    return any(e.kind in ("famine", "game_over") for e in result.events)


def food_lasts(month: Month, orders: list[Order], to_spring: bool = False) -> bool:
    """@brief The winter check: the month runs on a copy (trades filled in
    full, then the plan), then month after month with no orders.
    October to March: no famine until the end of March. Other months: no
    famine this month and one month of eating left.
    @param to_spring True: until the end of the next March in any month (a
           food sale, which cannot be undone in winter)."""
    trades = [o for o in orders if isinstance(o, TradeOrder)]
    others = [o for o in orders if not isinstance(o, TradeOrder)]
    trial = state_after_trades(month.state, trades, month.market, month.config, month.realm_key)
    result = resolve_turn(trial, others, month.config)
    if _famine(result):
        return False
    now = month_of(month.state.turn)
    if now not in FOOD_WATCH_MONTHS and not to_spring:
        return result.state.food >= food_needed(result.state, month.config)
    months_left = (LAST_WINTER_MONTH - now) % 12
    if to_spring and months_left == 0:
        # Why: in March "the end of March" is this very month; a sale must look
        # to the next one (game 28's states: Brenna, poor in food, would have
        # sold 4 lots in March and then starved in spring).
        months_left = 12
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


def _lots_free(month: Month, items: list[Item]) -> int:
    """@brief Lots the merchants can still handle this month after the plan's
    trades. Why: game 27, Brenna told to buy wood the month its market opened,
    with no merchant yet (TRADE_CAPACITY). Without a cap, no limit."""
    capacity = trade_capacity(month.state, month.config)
    if capacity is None:
        return MAX_SELL_LOTS * 100
    planned = sum(i.order.lots for i in items if isinstance(i.order, TradeOrder))
    return max(0, capacity - planned)


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
        lots = min(-(-(need - left[good]) // lot), left["gold"] // buy_price(month.market, month.config, good),
                   _lots_free(month, items))
        if lots < 1:
            continue
        what = labels.lots_of(lots, good)
        return (f"Tesoriere, compra al mercato {what}.",
                f"Direttiva: comprare {what}: {labels.GOODS_IT[good]} per meno di {BUY_COVER_MONTHS} mesi "
                f"di bisogno ({left[good]} contro {need}) (R7).")
    return None


def _food_lots_to_sell(month: Month, orders: list[Order], left_food: int) -> int:
    """@brief Food lots the realm can sell and still reach the end of the next
    March on at least the normal ration (the engine's seasons, month by month).
    Why: game 28, Aurelia kept 1,400-2,000 food from August and never sold:
    the old rule kept 2-3 months of gross eating (about 2,800), though about
    1,425 took it to spring, while Brenna fell on the reduced ration."""
    lot = month.config.market.lot_units
    trial = month
    if month.state.ration == "reduced":
        normal = copy.deepcopy(month.state)
        normal.ration = "normal"
        trial = Month(normal, month.config, month.market, month.realm_key)
    # Why: game 29, Brenna's plan cut the ration to reduced, so the food
    # "lasted" and the realm was told to sell 4 lots in November and December.
    orders = [o for o in orders if not (isinstance(o, SetRationOrder) and o.ration == "reduced")]
    for lots in range(min(MAX_SELL_LOTS, left_food // lot), 0, -1):
        sale = parse_order({"action": "trade", "good": "food", "side": "sell", "lots": lots})[0]
        if food_lasts(trial, orders + [sale], to_spring=True):
            return lots
    return 0


def _sell_directive(month: Month, items: list[Item], left: dict[str, int]) -> tuple[str, str] | None:
    """@brief R5: gold short and a good above its needs: sell the one that
    brings the most gold. R5b: gold not short, the same but a good sells only
    at its start price or above (no selling off into a full warehouse).
    Food, both: only what still takes the realm to the next spring.
    Why R5b: in game 25 Aurelia, rich in food, piled up 1858 food with enough
    gold, while Brenna, poor in food, ended on the reduced ration."""
    monthly_costs = costs(month.state, month.config)
    gold_short = left["gold"] < GOLD_SHORT_MONTHS * monthly_costs
    lot = month.config.market.lot_units
    orders = [i.order for i in items]
    best = None
    for good in ("food", "wood", "stone"):
        # Why: a good the plan buys looks plentiful after the purchase (game 25,
        # Brenna in May: told to sell the very wood its plan was buying).
        if _trades_good(items, good, "sell") or _trades_good(items, good, "buy"):
            continue
        book = month.market.goods[good]
        if not gold_short and book.price < month.config.market.start_price[good]:
            continue
        if good == "food":
            lots = _food_lots_to_sell(month, orders, left["food"])
        else:
            keep = need_ahead(month.state, month.config, good, SELL_KEEP_MONTHS) + SELL_KEEP_LOTS * lot
            lots = min(MAX_SELL_LOTS, max(0, (left[good] - keep) // lot))
        lots = min(lots, _lots_free(month, items))
        gold = lots * sell_price(month.market, month.config, good)
        if lots >= 1 and (best is None or gold > best[2]):
            best = (good, lots, gold)
    if best is None:
        return None
    good, lots, _ = best
    what = labels.lots_of(lots, good)
    if not gold_short:
        return (f"Tesoriere, vendi al mercato {what}.",
                f"Direttiva: vendere {what}: è più di quanto serve al regno, e il prezzo regge (R5b).")
    return (f"Tesoriere, vendi al mercato {what}.",
            f"Direttiva: vendere {what}: l'oro ({left['gold']}) copre meno di {GOLD_SHORT_MONTHS} mesi di "
            f"spese ({monthly_costs} al mese) (R5).")


def _market_directive(month: Month, items: list[Item], left: dict[str, int]) -> tuple[str, str] | None:
    """@brief R10: no market yet: build it once the wood also covers the
    firewood until spring (the start wood is just the first winter's firewood)."""
    if any(b.kind == "market" for b in month.state.buildings):
        return None
    if any(isinstance(i.order, BuildOrder) and i.order.building == "market" for i in items):
        return None
    cost = month.config.buildings["market"].wood
    firewood = need_ahead(month.state, month.config, "wood", months_to_spring(month.state.turn))
    if left["wood"] < cost + firewood:
        return None
    return ("Architetta, costruisci il mercato nella sua zona: senza mercato il regno non può commerciare.",
            f"Direttiva: costruire il mercato: il legno ({left['wood']}) basta per il cantiere ({cost}) e per la "
            f"legna fino a primavera ({firewood}) (R10).")


def _merchants_directive(month: Month, items: list[Item]) -> tuple[str, str] | None:
    """@brief R10: a market without merchants trades nothing."""
    if month.state.workers.trade > 0:
        return None
    if any(isinstance(i.order, AssignWorkersOrder) and i.order.trade > 0 for i in items):
        return None
    return (f"Architetta, metti {MERCHANTS_WANTED} adulti al mercato: senza mercanti non si commercia.",
            f"Direttiva: {MERCHANTS_WANTED} mercanti al mercato: è finito ma nessuno ci lavora (R10).")


def _watchtower_directive(month: Month, items: list[Item], left: dict[str, int]) -> tuple[str, str] | None:
    """@brief R11: after the first raid, a watchtower (no guards without it),
    once the wood also covers the firewood until spring, as R10.
    Why after a raid: the design wants the early raids to be the lesson that
    makes the realm want the Gastaldo (docs/DESIGN.md)."""
    config = month.config
    if config.bandits is None or not month.raided:
        return None
    if any(b.kind == "watchtower" for b in month.state.buildings):
        return None
    if any(isinstance(i.order, BuildOrder) and i.order.building == "watchtower" for i in items):
        return None
    spec = config.buildings["watchtower"]
    firewood = need_ahead(month.state, config, "wood", months_to_spring(month.state.turn))
    if left["wood"] < spec.wood + firewood or left["stone"] < spec.stone:
        return None
    return ("Architetta, costruisci la torre di guardia nella sua zona: i briganti hanno già colpito, e senza "
            "torre non si possono tenere guardie.",
            f"Direttiva: costruire la torre di guardia dopo un assalto: legno ({left['wood']}) per il cantiere "
            f"({spec.wood}) e la legna fino a primavera ({firewood}), pietra ({left['stone']}) per il cantiere "
            f"({spec.stone}) (R11).")


def directive(month: Month, items: list[Item]) -> tuple[str, str] | None:
    """@brief At most one directive: (text for the council, reason) or None.
    R10 first where the market is a building (no trade without it), R11 after
    a raid, then R7 before R5: a need first."""
    status = market_status(month.state, month.config)
    if month.market is None or status == "none":
        return None
    accepted = [i for i in items if i.accepted]
    left = _remaining(month, [i.order for i in accepted])
    if status == "unbuilt":
        return _market_directive(month, accepted, left)
    if month.config.market.needs_building:
        staff = _merchants_directive(month, accepted)
        if staff:
            return staff
    return (_watchtower_directive(month, accepted, left) or _buy_directive(month, accepted, left)
            or _sell_directive(month, accepted, left))


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

def _stone_runs_short(month: Month) -> bool:
    """@brief The stone covers less than BUY_COVER_MONTHS of upkeep (R7's measure)."""
    return month.state.stone < need_ahead(month.state, month.config, "stone", BUY_COVER_MONTHS)


def _farmers_off(month: Month, item: Item) -> str:
    if item.raw.get("action") != "assign_workers" or month_of(month.state.turn) not in FOOD_WATCH_MONTHS:
        return ""
    taken = month.state.workers.food - item.order.food
    if taken <= 0:
        return ""
    # Why: stone upkeep left short halves every building, farms included, so
    # hands moved to the quarry raise the food. Game 34: R2 excluded exactly
    # that cure (Aurelia, October of year 2, stone 3 of 15) and the realm
    # starved. The winter check below still weighs the plan as a whole.
    if _stone_runs_short(month) and item.order.stone > month.state.workers.stone:
        return ""
    return f"toglie {taken} contadini ai campi tra l'autunno e l'inverno (R2)"


def _claim_in_winter(month: Month, item: Item) -> str:
    if item.raw.get("action") == "claim_tiles" and season_of(month.state.turn) == "winter":
        return "niente nuove terre d'inverno: l'oro serve al mercato (R3)"
    return ""


def _tax_cut(month: Month, item: Item) -> str:
    if item.raw.get("action") != "set_tax" or item.order.rate >= month.state.tax_rate:
        return ""
    # The merchants pay their own tax, not this one (workers.trade is 0 elsewhere).
    taxed_adults = month.state.adults - month.state.workers.trade
    income = taxed_adults * item.order.rate // month.config.economy.tax_divisor
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
    spec = month.config.buildings[item.order.building]
    if not spec.jobs and not spec.housing:
        return ""  # a building with no places (the watchtower) cannot stand empty
    empty, one_building = _empty_places(month, item.order.building)
    if empty * 2 < one_building:
        return ""
    what = "posti letto" if item.order.building == "house" else "posti di lavoro"
    return f"ci sono già {empty} {what} vuoti (R8)"


def _improved_jobs(month: Month, sector: str, skip_id: int) -> int:
    """@brief Jobs of the sector's working buildings that have tools or are getting them."""
    config, state = month.config, month.state
    return sum(config.buildings[b.kind].jobs for b in state.buildings
               if b.id != skip_id and not b.turns_left and (b.level or b.improving)
               and config.buildings[b.kind].sector == sector and building_works(state, config, b))


def _idle_tools(month: Month, item: Item, orders: list[Order]) -> str:
    """@brief R13: tools only where the workers fill them, and not at the cost
    of the firewood until spring (lab/village_tools.py: the poor-wood site
    bought tools in January with its start wood and fell to the cold).
    @param orders The plan's other orders (their assignment, their wood)."""
    if not isinstance(item.order, ImproveOrder):
        return ""
    config, state = month.config, month.state
    building = next((b for b in state.buildings if b.id == item.order.building_id), None)
    if building is None:
        return ""
    spec = config.buildings[building.kind]
    assigned = next((o for o in orders if isinstance(o, AssignWorkersOrder)), state.workers)
    workers = getattr(assigned, spec.sector)
    wanted = _improved_jobs(month, spec.sector, building.id) + spec.jobs // 2
    if workers < wanted:
        return f"i suoi posti non sarebbero pieni: {workers} lavoratori, ne servono {wanted} (R13)"
    short = _firewood_short(month, orders + [item.order])
    return f"{short} (R13)" if short else ""


def _firewood_short(month: Month, orders: list[Order]) -> str:
    """@brief The firewood check of R13 and R10b: the wood left after the
    plan, plus the wood the plan's woodcutters cut until spring, against the
    firewood until spring. Empty when it is enough, else the reason (no rule tag).
    @param orders The whole plan, the weighed order included."""
    state, config = month.state, month.config
    assigned = next((o for o in orders if isinstance(o, AssignWorkersOrder)), state.workers)
    months = months_to_spring(state.turn)
    firewood = need_ahead(state, config, "wood", months)
    workers = Workers(assigned.food, assigned.wood, assigned.stone, assigned.clearing, assigned.trade)
    left = _remaining(month, orders)["wood"] + wood_ahead(state, config, months, workers)
    if left >= firewood:
        return ""
    return f"il legno che resta, con quello tagliato fino a primavera ({left}), non basta per la legna ({firewood})"


def _cold_build(month: Month, item: Item, orders: list[Order]) -> str:
    """@brief R10b: no build of the council's own at the cost of the firewood
    until spring, the check R10 and R11 make on their own directives.
    Why: game 40, month 2, Elsina's Architect built the market itself and
    R10's check never ran: 36 wood left, 16 short of the firewood to March.
    @param orders The plan's other orders (their assignment, their wood)."""
    if not isinstance(item.order, BuildOrder) or not month.config.buildings[item.order.building].wood:
        return ""
    short = _firewood_short(month, orders + [item.order])
    return f"{short} (R10b)" if short else ""


def _useless_buy(month: Month, item: Item, others: list[Order]) -> str:
    order = item.order
    if not isinstance(order, TradeOrder) or order.side != "buy" or order.good == "food":
        return ""
    months = months_to_spring(month.state.turn) if order.good == "wood" else USELESS_BUY_MONTHS
    need = need_ahead(month.state, month.config, order.good, months)
    left = _remaining(month, others)[order.good]
    if left < need:
        return ""
    if order.good == "wood":
        return f"il legno basta già fino alla fine dell'inverno ({left} contro {need}) (R4b)"
    return f"la pietra basta già per {USELESS_BUY_MONTHS} mesi ({left} contro {need}) (R4b)"


def _costly_feast(month: Month, item: Item, kept: list[Order]) -> str:
    if item.raw.get("action") != "hold_feast":
        return ""
    gold_left = _remaining(month, kept)["gold"]
    monthly_costs = costs(month.state, month.config)
    if gold_left >= monthly_costs:
        return ""
    return f"resterebbero {gold_left} oro, meno delle spese del mese ({monthly_costs}) (R9)"


RATION_ORDER = ("reduced", "normal", "abundant")


def _richer_ration(month: Month, item: Item, kept: list[Order]) -> str:
    """@brief R2b: a richer ration when the food does not last with it.
    Why: R2 drops an order only when the food lasts without it; with an empty
    granary nothing helps, so in game 27 Brenna (food 0) and Aurelia (half a
    month of food) kept the abundant ration from July and ate their surplus."""
    if item.raw.get("action") != "set_ration":
        return ""
    if RATION_ORDER.index(item.order.ration) <= RATION_ORDER.index(month.state.ration):
        return ""
    if food_lasts(month, kept):
        return ""
    return "con la razione più ricca il cibo non basta (R2b)"


def exclusions(month: Month, items: list[Item], granted: dict | None,
               laws_locked: bool = False) -> list[tuple[int, str]]:
    """@brief Plan items to leave out, with their reasons: (index, reason).
    Only items the engine check accepted; a granted petition runs first.
    @param granted The granted petition's order, or None.
    @param laws_locked True in an automatic month of a seasonal game (R12):
           every law item goes first, so the other rules weigh the plan
           without it."""
    first = [parse_order(granted)[0]] if granted else []
    kept = [i for i in items if i.accepted and not (granted and i.raw.get("action") == granted.get("action"))]
    excluded: list[tuple[int, str]] = []
    if laws_locked:
        for item in [i for i in kept if i.raw.get("action") in LAWS]:
            excluded.append((item.index, LOCKED_LAW))
            kept.remove(item)

    def orders_without(item: Item) -> list[Order]:
        return first + [i.order for i in kept if i is not item]

    for item in list(kept):
        reason = (_farmers_off(month, item) or _claim_in_winter(month, item) or _tax_cut(month, item)
                  or _empty_building(month, item) or _useless_buy(month, item, orders_without(item))
                  or _idle_tools(month, item, orders_without(item))
                  or _cold_build(month, item, orders_without(item)))
        if reason:
            excluded.append((item.index, reason))
            kept.remove(item)
    for item in list(kept):
        orders = first + [i.order for i in kept]
        reason = _costly_feast(month, item, orders) or _richer_ration(month, item, orders)
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
