"""@brief The common market of a game: one warehouse on consignment.

docs/DESIGN.md, "Market, needs and land levels"; values from
lab/market_closed.py. Pure and integer-only, like the turn.

- A sale hands the goods over at once; the seller is paid when a buyer takes
  them, oldest sale first. Goods on sale cannot be taken back.
- The warehouse owns nothing but a start stock, nobody's goods (MERCHANT):
  the only goods from outside, once. Its gold leaves the game.
- One price per good, gold per lot. Buyers pay price + margin, sellers get
  price - margin; the margin leaves the game.
- Every month all realms' trades are filled together at the published price:
  sales first, then purchases, split pro rata when the warehouse is short.
  Then the price moves: up if more lots were asked than there were, down if
  the realms' goods on sale exceed cover_months of recently asked lots.
- Food in the warehouse spoils like the granaries.

A month of the whole game (resolve_month): check every realm's trades,
fill them, give each realm its goods and gold, then resolve each realm's
turn with its other orders. The replay runs the same function.
"""

import copy
from dataclasses import asdict, dataclass, field

from engine.config import Config
from engine.orders import Order, TradeOrder
from engine.people import PeopleChoice
from engine.state import Event, GameState
from engine.turn import TurnResult, resolve_turn
from engine.validator import OrderResult, PlanReport, check_plans

GOODS = ("food", "wood", "stone")
MERCHANT = ""  # seller of the start stock: nobody is paid for it


@dataclass
class Consignment:
    seller: str  # realm key (the server uses the realm id as text)
    units: int


@dataclass
class GoodBook:
    price: int  # gold per lot this month (mid price, before the margin)
    queue: list[Consignment]  # goods on sale, oldest first
    recent_asked: list[int] = field(default_factory=list)  # lots asked, last months, oldest first
    last_bought: int = 0  # units bought last month (public)
    last_sold: int = 0  # units put on sale last month (public)


@dataclass
class MarketState:
    goods: dict[str, GoodBook]


@dataclass
class RealmMonth:
    """@brief One realm's input to a month of the game."""
    state: GameState
    orders: list[Order]
    people: PeopleChoice | None = None


def new_market(config: Config, realm_count: int) -> MarketState:
    """@brief The warehouse at game start: start prices and the start stock."""
    market_cfg = config.market
    return MarketState({
        good: GoodBook(market_cfg.start_price[good],
                       [Consignment(MERCHANT, market_cfg.start_stock_per_realm[good] * realm_count)])
        for good in GOODS
    })


def market_to_dict(market: MarketState) -> dict:
    return asdict(market)


def market_from_dict(data: dict) -> MarketState:
    goods = {}
    for good, book in data["goods"].items():
        fields = dict(book)
        fields["queue"] = [Consignment(**c) for c in fields["queue"]]
        goods[good] = GoodBook(**fields)
    return MarketState(goods)


def buy_price(market: MarketState, config: Config, good: str) -> int:
    """@brief Gold per lot bought: price + margin, rounded up (never no margin)."""
    return -(-market.goods[good].price * (100 + config.market.margin_pct) // 100)


def sell_price(market: MarketState, config: Config, good: str) -> int:
    """@brief Gold per lot sold: price - margin, rounded down."""
    return market.goods[good].price * (100 - config.market.margin_pct) // 100


def stock(book: GoodBook, include_start_stock: bool = True) -> int:
    """@brief Units on sale (the start stock included unless told otherwise)."""
    return sum(c.units for c in book.queue if include_start_stock or c.seller != MERCHANT)


def check_trades(state: GameState, orders: list[TradeOrder], market: MarketState,
                 config: Config) -> tuple[dict[str, int], list[OrderResult]]:
    """@brief Validate a realm's trades against its stock and gold, in priority
    order; each accepted trade commits its goods or gold before the next.
    @return ({good: lots, > 0 buy, < 0 sell}, one result per order). An
            accepted trade may still be filled only in part (pro rata).
    """
    lot = config.market.lot_units
    requests: dict[str, int] = {}
    gold_left = state.gold
    goods_left = {good: getattr(state, good) for good in GOODS}
    results = []
    for order in sorted(orders, key=lambda o: o.priority):
        signed = order.lots if order.side == "buy" else -order.lots
        if requests.get(order.good, 0) * signed < 0:
            results.append(OrderResult(order, False, "BOTH_SIDES", f"already trading {order.good} the other way"))
            continue
        if order.side == "sell":
            if goods_left[order.good] < order.lots * lot:
                results.append(OrderResult(order, False, "INSUFFICIENT_RESOURCES",
                                           f"{order.lots} lots need {order.lots * lot} {order.good}"))
                continue
            goods_left[order.good] -= order.lots * lot
        else:
            cost = order.lots * buy_price(market, config, order.good)
            if gold_left < cost:
                results.append(OrderResult(order, False, "INSUFFICIENT_RESOURCES", f"{cost} gold needed"))
                continue
            gold_left -= cost
        requests[order.good] = requests.get(order.good, 0) + signed
        results.append(OrderResult(order, True))
    return requests, results


def check_month_plan(state: GameState, orders: list[Order], market: MarketState | None,
                     config: Config) -> PlanReport:
    """@brief Dry run of a realm's month as resolve_month runs it: trades first,
    then the other orders on the state the trades leave. For the council's cost
    check and the sovereign's preview; the state is NOT modified.

    Assumption: every accepted purchase is filled in full and the gold of
    sales arrives later (the warehouse is shared, so the real fill is known
    only when every realm has traded).
    @return Verdicts in the order of the input list (not the evaluation order,
            so callers can pair them with their items); spent and remaining
            against the state given (a purchase shows as negative spending).
    """
    trades = [o for o in orders if isinstance(o, TradeOrder)]
    trial, trade_results, others = state, [], orders
    if market is not None and config.market is not None and trades:
        _, trade_results = check_trades(state, trades, market, config)
        trial = _after_full_fills(state, trade_results, market, config)
        others = [o for o in orders if not isinstance(o, TradeOrder)]
    report = check_plans(trial, others, config)
    by_order = {id(r.order): r for r in trade_results + report.results}
    resources = ("food", "wood", "stone", "gold")
    spent = {name: getattr(state, name) - report.remaining[name] for name in resources}
    return PlanReport([by_order[id(o)] for o in orders], spent, report.remaining)


def _after_full_fills(state: GameState, trade_results: list[OrderResult], market: MarketState,
                      config: Config) -> GameState:
    """@brief A copy of the state as if every accepted trade were filled in full."""
    trial = copy.deepcopy(state)
    lot = config.market.lot_units
    for verdict in trade_results:
        if not verdict.accepted:
            continue
        order = verdict.order
        units = order.lots * lot if order.side == "buy" else -order.lots * lot
        setattr(trial, order.good, getattr(trial, order.good) + units)
        if order.side == "buy":
            trial.gold -= order.lots * buy_price(market, config, order.good)
    return trial


def _take_oldest(book: GoodBook, units: int) -> dict[str, int]:
    """@brief Remove units from the oldest consignments. @return {seller: units}."""
    taken: dict[str, int] = {}
    while units > 0 and book.queue:
        first = book.queue[0]
        part = min(units, first.units)
        taken[first.seller] = taken.get(first.seller, 0) + part
        first.units -= part
        units -= part
        if first.units == 0:
            book.queue.pop(0)
    return taken


def _move_price(book: GoodBook, good: str, config: Config, asked: int, available: int) -> None:
    """@brief Up when demand was not met, down when the realms' goods are not
    moving. The start stock never counts as too much: nobody asked for it."""
    market_cfg = config.market
    book.recent_asked = (book.recent_asked + [asked])[-market_cfg.cover_months:]
    step = max(1, book.price * market_cfg.step_pct // 100)
    if asked > available:
        book.price += step
    elif stock(book, include_start_stock=False) // market_cfg.lot_units > sum(book.recent_asked):
        book.price -= step
    start = market_cfg.start_price[good]
    low = max(1, start * market_cfg.min_price_pct // 100)
    high = start * market_cfg.max_price_pct // 100
    book.price = min(high, max(low, book.price))


def resolve_market(market: MarketState, requests: dict[str, dict[str, int]],
                   config: Config) -> tuple[MarketState, dict[str, dict[str, int]], dict[str, int]]:
    """@brief Fill one month of trades, all realms together.
    @param market State at the start of the month; NOT modified.
    @param requests {realm: {good: lots}} from check_trades.
    @return (new market, fills {realm: {good: lots, same signs}}, gold paid to
            each seller {realm: gold}). Buyers pay at the month's price.
    """
    lot = config.market.lot_units
    new = copy.deepcopy(market)
    realms = sorted(requests)  # a fixed order: the result never depends on the caller's
    fills: dict[str, dict[str, int]] = {realm: {} for realm in realms}
    paid: dict[str, int] = {}
    for good, book in new.goods.items():
        unit_pay = sell_price(market, config, good)
        book.last_sold = 0
        for realm in realms:
            lots = requests[realm].get(good, 0)
            if lots < 0:
                book.queue.append(Consignment(realm, -lots * lot))
                book.last_sold += -lots * lot
                fills[realm][good] = lots
        asked = {realm: requests[realm][good] for realm in realms if requests[realm].get(good, 0) > 0}
        total = sum(asked.values())
        available = stock(book) // lot
        book.last_bought = 0
        for realm, lots in asked.items():
            granted = lots if total <= available else lots * available // total
            fills[realm][good] = granted
            book.last_bought += granted * lot
            for seller, units in _take_oldest(book, granted * lot).items():
                if seller != MERCHANT:
                    paid[seller] = paid.get(seller, 0) + units * unit_pay // lot
        _move_price(book, good, config, total, available)
    _spoil(new, config)
    return new, fills, paid


def _spoil(market: MarketState, config: Config) -> None:
    """@brief Food on sale rots like food in the granaries."""
    book = market.goods["food"]
    for consignment in book.queue:
        consignment.units -= consignment.units * config.economy.food_spoilage_pct // 100
    book.queue = [c for c in book.queue if c.units > 0]


def apply_trade(state: GameState, fills: dict[str, int], gold_paid: int, market: MarketState,
                config: Config) -> list[Event]:
    """@brief Give a realm what the market filled: goods in, the price of its
    purchases out, the gold of its goods sold (this month or earlier) in.
    @param market The market at the start of the month (its prices).
    @return The realm's trade events.
    """
    lot = config.market.lot_units
    events = []
    for good, lots in fills.items():
        if lots > 0:
            gold = lots * buy_price(market, config, good)
            setattr(state, good, getattr(state, good) + lots * lot)
            state.gold -= gold
            events.append(Event("trade_bought", {"good": good, "lots": lots, "gold": gold}))
        elif lots < 0:
            setattr(state, good, getattr(state, good) + lots * lot)
            events.append(Event("trade_on_sale", {"good": good, "lots": -lots}))
    if gold_paid:
        state.gold += gold_paid
        events.append(Event("trade_paid", {"gold": gold_paid}))
    return events


def resolve_month(market: MarketState | None, realms: dict[str, RealmMonth],
                  config: Config) -> tuple[MarketState | None, dict[str, TurnResult]]:
    """@brief One month of the whole game: the market first, then each realm.
    @param market None for a game without a market: trades reach the turn
           and are refused there (NO_MARKET).
    @param realms {realm key: RealmMonth} of the realms still playing.
    @return (market at the start of next month, {realm key: TurnResult}). A
            realm's results list its trades first, then its other orders.
    """
    if market is None or config.market is None:
        return market, {key: resolve_turn(r.state, r.orders, config, r.people) for key, r in realms.items()}
    requests, trade_results = {}, {}
    for key, realm in realms.items():
        trades = [o for o in realm.orders if isinstance(o, TradeOrder)]
        requests[key], trade_results[key] = check_trades(realm.state, trades, market, config)
    new_market, fills, paid = resolve_market(market, requests, config)
    for key, verdicts in trade_results.items():
        for verdict in verdicts:  # an accepted purchase may get fewer lots (pro rata)
            good = verdict.order.good
            if verdict.accepted and verdict.order.side == "buy":
                verdict.message = f"filled {fills[key][good]} of {requests[key][good]} lots of {good} asked this month"
    results = {}
    for key, realm in realms.items():
        state = copy.deepcopy(realm.state)
        events = apply_trade(state, fills[key], paid.get(key, 0), market, config)
        others = [o for o in realm.orders if not isinstance(o, TradeOrder)]
        turn = resolve_turn(state, others, config, realm.people)
        results[key] = TurnResult(turn.state, trade_results[key] + turn.order_results, events + turn.events)
    return new_market, results
