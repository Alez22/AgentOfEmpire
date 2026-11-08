"""@brief Market lab, closed market: three realms of different land trade
through one warehouse on consignment. Nothing comes from outside.

Usage: docker compose run --rm -T tests python lab/market_closed.py [eight]
  (no argument: three realms, a granary, a forest and a quarry; "eight":
  eight realms with three levels per resource, see main_eight)

Follows lab/market_sim.py (outside merchant with restock, 2026-11-08). The
sovereign asked for a market with no goods or gold from outside, and realms
that differ so they have something to trade (no Ambassador, no bilateral
deals in this step).

The market:
- a warehouse on consignment: a realm that sells hands over its goods at
  once, and is paid only when a buyer takes them, first in first out;
- the warehouse has no gold and no goods of its own: everything in it comes
  from the realms;
- the stored food spoils like the granaries (food_spoilage_pct, rounded down);
- one price per good, gold per lot of 50. Buyers pay price + margin, sellers
  get price - margin; the margin leaves the game (the gold sink);
- purchases are filled from the warehouse at the month's price, all realms
  together; when it is short, it is split in proportion to the lots asked;
- then the price moves by step_pct: up if the month asked more than there
  was, down if goods stayed unsold, within min_pct..max_pct of the start
  price.

The realms differ only in what their workers yield (the map is the same:
a first test before redrawing the world). Every realm plays the same
policy, so the differences come from the land alone:
- workers: food up to the farm jobs, 4 on wood and 2 on stone; a sector
  whose yield is above the base gets twice the hands;
- trade first: buy food up to 1.5 months, buy the wood and stone missing
  for the next building; sell the food above 2 months (3 from August to
  December, before the winter), the wood above 120, the stone above 100;
- then orders, knowing what the market gave: the ration rule (reduced below
  1 month, normal above 1.5), a farm when there is room, else a house when
  housing runs short.

Steady needs for wood and stone (variants A and B, 2026-11-08: in the first
run nobody bought wood or stone, because a realm builds little in its core):
- A, firewood: every winter month (January to March, the engine's winter)
  the realm burns 1 wood per firewood_people people; what is missing hits
  the mood at once, shock_per_pct per missing percent (like a famine);
- B, upkeep in stone: every month 1 stone per stone_buildings active
  buildings; what is missing lowers that month's output by half the
  missing share (as unpaid gold upkeep halves it);
- the policy keeps the wood for the next 4 months of firewood and the stone
  for 4 months of upkeep, plus the next building; it buys below that and
  sells above it (at least 120 wood and 100 stone kept).

Limits, on purpose:
- The needs are applied by this script, like the market: not engine rules.
- The market is applied by this script before each resolve_turn; it is not
  an engine order (no validator, no events, no replay).
- Goods on consignment cannot be taken back.
- A fixed policy is not a council: it shows prices, flows and edges.
- No claims of new land: every realm stays in its core.
"""

import dataclasses
import sys

from engine import load_config, new_game, resolve_turn
from engine.territory import find_place
from engine.turn import food_needed, housing_capacity, jobs_in_sector
from lab.market_sim import GOODS, LOT, SALARY, _affordable, _lots_short, _months_of_food, _order

MONTHS = 24
BEFORE_WINTER = (7, 8, 9, 10, 11)  # month index, August to December
BASE_OUTPUT = {"food": 15, "wood": 6, "stone": 4}  # per worker, as in config.toml
KEEP = {"wood": 120, "stone": 100}
SECTOR_BUILDING = {"food": "farm", "wood": "sawmill", "stone": "quarry"}


@dataclasses.dataclass
class Consignment:
    seller: str
    units: int


@dataclasses.dataclass
class GoodBook:
    """@brief One good in the warehouse. Integers only."""
    start_price: int  # gold per lot at the start; bounds are relative to it
    price: int
    queue: list  # Consignment, oldest first
    recent_asked: list = dataclasses.field(default_factory=list)  # lots asked, last months, oldest first

    def stock(self) -> int:
        return sum(c.units for c in self.queue)


@dataclasses.dataclass
class Needs:
    """@brief Variants A and B; 0 turns a need off."""
    firewood_people: int = 2  # 1 wood per this many people, per winter month
    shock_per_pct: int = 2  # mood lost per missing percent of firewood
    stone_buildings: int = 2  # stone_per stone per this many active buildings, per month
    stone_per: int = 1
    firewood_months: tuple = (0, 1, 2)  # month index; default the engine's winter (season_of)


NO_NEEDS = Needs(firewood_people=0, stone_buildings=0)


@dataclasses.dataclass
class Rules:
    margin_pct: int = 10
    step_pct: int = 10
    min_pct: int = 50
    max_pct: int = 300
    spoil_pct: int = 2  # food only
    # "cover" (2026-11-08): down only when the stock is more than cover_months
    # of the recent demand; "unsold": down whenever a lot stayed unsold (the
    # first rule: a few old lots kept the price at the floor).
    price_rule: str = "cover"
    cover_months: int = 3
    # Units in the warehouse at game start, nobody's goods (the only goods
    # from outside, once): something to buy in the first winter.
    start_stock: dict = dataclasses.field(default_factory=dict)
    # False (2026-11-08): the start stock does not count as "too much" in
    # the price rule; nobody asked for it yet, and counting it made the
    # stone price fall from 20 to 10 without one sale.
    start_stock_in_price: bool = True


START_STOCK = {"food": 300, "wood": 150, "stone": 100}
MERCHANT = "merchant"  # seller of the start stock; its gold leaves the game


def new_books(rules, food=10, wood=15, stone=20):
    """@brief Warehouse at game start, with the rules' start stock; start
    prices per lot of 50, as in market_sim.py."""
    books = {g: GoodBook(p, p, []) for g, p in (("food", food), ("wood", wood), ("stone", stone))}
    for good, units in rules.start_stock.items():
        books[good].queue.append(Consignment(MERCHANT, units))
    return books


def buy_price(book, rules):
    return -(-book.price * (100 + rules.margin_pct) // 100)


def sell_price(book, rules):
    return book.price * (100 - rules.margin_pct) // 100


def _take_fifo(book, units):
    """@brief Remove units from the oldest consignments.
    @return {seller: units taken}."""
    taken = {}
    while units > 0 and book.queue:
        first = book.queue[0]
        part = min(units, first.units)
        taken[first.seller] = taken.get(first.seller, 0) + part
        first.units -= part
        units -= part
        if first.units == 0:
            book.queue.pop(0)
    return taken


def _too_much_stock(book, rules):
    """@brief True when the price should fall because goods are not moving."""
    stock_lots = book.stock() // LOT
    if not rules.start_stock_in_price:
        stock_lots = sum(c.units for c in book.queue if c.seller != MERCHANT) // LOT
    if rules.price_rule == "unsold":
        return stock_lots >= 1
    # More on the shelf than cover_months of what was asked lately. With no
    # demand at all, any stock is too much.
    return stock_lots > sum(book.recent_asked)


def _move_price(book, rules, asked_lots, available_lots):
    """@brief Up when demand was not met, down when goods are not moving."""
    book.recent_asked = (book.recent_asked + [asked_lots])[-rules.cover_months:]
    step = max(1, book.price * rules.step_pct // 100)
    if asked_lots > available_lots:
        book.price += step
    elif _too_much_stock(book, rules):
        book.price -= step
    low = max(1, book.start_price * rules.min_pct // 100)
    high = book.start_price * rules.max_pct // 100
    book.price = min(high, max(low, book.price))


def resolve_market(books, rules, requests):
    """@brief One month of the warehouse, all realms together.
    @param books {good: GoodBook}; changed in place.
    @param requests {realm: {good: lots}}, > 0 buy, < 0 sell. The caller has
           checked that sellers own the goods and buyers can pay.
    @return (fills {realm: {good: lots}}, paid_to_sellers {realm: gold}).
            Purchases are paid at the price of the month, before it moves.
    """
    fills = {realm: {} for realm in requests}
    paid = {realm: 0 for realm in requests}
    for good, book in books.items():
        for realm, wanted in requests.items():
            if wanted.get(good, 0) < 0:
                book.queue.append(Consignment(realm, -wanted[good] * LOT))
                fills[realm][good] = wanted[good]
        asked = {realm: w[good] for realm, w in requests.items() if w.get(good, 0) > 0}
        total = sum(asked.values())
        available = book.stock() // LOT
        unit_pay = sell_price(book, rules)
        for realm, lots in asked.items():
            granted = lots if total <= available else lots * available // total
            fills[realm][good] = granted
            for seller, units in _take_fifo(book, granted * LOT).items():
                # A realm whose game is over still has goods here: they sell, the gold is lost.
                paid[seller] = paid.get(seller, 0) + units * unit_pay // LOT
        _move_price(book, rules, total, available)
    return fills, paid


def spoil(books, rules):
    """@brief Food on consignment rots like food in the granaries."""
    for c in books["food"].queue:
        c.units -= c.units * rules.spoil_pct // 100


def realm_config(base, yields):
    """@brief Copy of the config with other outputs per worker, e.g. {"food": 18}."""
    buildings = dict(base.buildings)
    for sector, output in yields.items():
        kind = SECTOR_BUILDING[sector]
        buildings[kind] = dataclasses.replace(buildings[kind], output_per_worker=output)
    return dataclasses.replace(base, buildings=buildings)


def firewood_needed(state, needs, month):
    if not needs.firewood_people or month not in needs.firewood_months:
        return 0
    return state.population() // needs.firewood_people


def upkeep_stone_needed(state, needs):
    if not needs.stone_buildings:
        return 0
    active = sum(1 for b in state.buildings if b.turns_left == 0)
    return active * needs.stone_per // needs.stone_buildings


def _missing_pct(needed, taken):
    return (needed - taken) * 100 // needed if needed else 0


def consume_needs(state, config, needs):
    """@brief Burn the firewood and pay the stone upkeep of this month.
    @return (config for this month's turn, firewood missing %, stone missing %).
            With stone missing the config's outputs are lowered."""
    month = (state.turn - 1) % 12
    firewood = firewood_needed(state, needs, month)
    burnt = min(firewood, state.wood)
    state.wood -= burnt
    cold_pct = _missing_pct(firewood, burnt)
    state.mood = max(0, state.mood - cold_pct * needs.shock_per_pct)
    upkeep = upkeep_stone_needed(state, needs)
    paid = min(upkeep, state.stone)
    state.stone -= paid
    worn_pct = _missing_pct(upkeep, paid)
    if worn_pct == 0:
        return config, cold_pct, 0
    lower = {sector: config.buildings[kind].output_per_worker * (100 - worn_pct // 2) // 100
             for sector, kind in SECTOR_BUILDING.items()}
    return realm_config(config, lower), cold_pct, worn_pct


def stock_targets(state, config, needs):
    """@brief Wood and stone the realm wants to hold: 4 months of needs plus
    the next building."""
    month = (state.turn - 1) % 12
    wood = sum(firewood_needed(state, needs, (month + ahead) % 12) for ahead in range(4))
    stone = 4 * upkeep_stone_needed(state, needs)
    kind = _next_building(state, config)
    if kind:
        wood += config.buildings[kind].wood
        stone += config.buildings[kind].stone
    return {"wood": wood, "stone": stone}


def _hands(config, sector, base_hands, low_price):
    """@brief Twice the hands for a sector this land is good at, unless its
    price has fallen below the start price (a realm that reacts to the market)."""
    better = config.buildings[SECTOR_BUILDING[sector]].output_per_worker > BASE_OUTPUT[sector]
    return 2 * base_hands if better and not low_price.get(sector) else base_hands


def _workers(state, config, low_price, stone_hands=2):
    """@brief stone_hands: the base hands on stone (2 at the start of the game)."""
    wood = min(_hands(config, "wood", 4, low_price), jobs_in_sector(state, config, "wood"))
    stone = min(_hands(config, "stone", stone_hands, low_price), jobs_in_sector(state, config, "stone"))
    food = min(jobs_in_sector(state, config, "food"), state.adults - wood - stone)
    return _order({"action": "assign_workers", "food": max(0, food), "wood": wood, "stone": stone})


def _next_building(state, config):
    """@brief The building the policy wants next, or None."""
    if find_place(state, config, "farm"):
        return "farm"
    if housing_capacity(state, config) - state.population() < 10 and find_place(state, config, "house"):
        return "house"
    return None


def trade_requests(state, config, prices, needs):
    """@brief What the realm asks the market this month: {good: lots}."""
    trade = {}
    need = food_needed(state, config)
    keep_gold = 20
    if _months_of_food(state, config) < 1.5:
        trade["food"] = _affordable(_lots_short(state.food, 3 * need // 2), prices["food"][0], state.gold, keep_gold)
    month = (state.turn - 1) % 12
    food_keep = (3 if month in BEFORE_WINTER else 2) * need
    if state.food - food_keep >= LOT:
        trade["food"] = -((state.food - food_keep) // LOT)
    for good, target in stock_targets(state, config, needs).items():
        have = getattr(state, good)
        if have < target:
            trade[good] = _affordable(_lots_short(have, target), prices[good][0], state.gold, keep_gold)
        elif have - max(KEEP[good], target + LOT) >= LOT:
            trade[good] = -((have - max(KEEP[good], target + LOT)) // LOT)
    return trade


def month_orders(state, config, low_price, stone_hands=2):
    """@brief Orders after the market: ration, workers, one building.
    @param low_price {good: True} for the goods whose price is below the start
           (empty when the realm does not react to prices)."""
    orders = []
    months = _months_of_food(state, config)
    if state.ration == "normal" and months < 1:
        orders.append(_order({"action": "set_ration", "ration": "reduced"}))
    elif state.ration == "reduced" and months > 1.5:
        orders.append(_order({"action": "set_ration", "ration": "normal"}))
    orders.append(_workers(state, config, low_price, stone_hands))
    kind = _next_building(state, config)
    spec = config.buildings[kind] if kind else None
    if spec and state.wood >= spec.wood and state.stone >= spec.stone and state.gold >= spec.gold:
        orders.append(_order({"action": "build", "building": kind}))
    return orders


class Realm:
    """@brief One realm, its land and its running numbers."""

    def __init__(self, name, config, seed):
        self.name, self.config = name, config
        self.state = new_game(config, seed)
        self.state.council_salary = SALARY
        self.lowest_food = self.state.food
        self.reduced_months = 0
        self.cold_months, self.worn_months = 0, 0
        self.spent, self.earned = 0, 0
        self.bought = {g: 0 for g in GOODS}
        self.sold = {g: 0 for g in GOODS}

    def apply(self, fills, prices, paid):
        for good, lots in fills.items():
            setattr(self.state, good, getattr(self.state, good) + lots * LOT)
            if lots > 0:
                self.state.gold -= lots * prices[good][0]
                self.spent += lots * prices[good][0]
                self.bought[good] += lots * LOT
            else:
                self.sold[good] += -lots * LOT
        self.state.gold += paid
        self.earned += paid

    def summary(self, books):
        s = self.state
        waiting = " ".join(f"{g} {sum(c.units for c in books[g].queue if c.seller == self.name)}" for g in GOODS) if books else "-"
        houses = sum(1 for b in s.buildings if b.kind == "house")
        farms = sum(1 for b in s.buildings if b.kind == "farm")
        trade = " ".join(f"{g} +{self.bought[g]}/-{self.sold[g]}" for g in GOODS)
        end = f" | {s.game_over} at month {s.turn - 1}" if s.game_over else ""
        return (f"gold {s.gold:>4} (spent {self.spent:>4}, earned {self.earned:>4}) | lowest food {self.lowest_food:>5}"
                f" | reduced {self.reduced_months:>2} m | cold {self.cold_months:>2} m | worn {self.worn_months:>2} m | pop {s.population():>3} | farms {farms} houses {houses:>2}"
                f" | mood {s.mood} {s.unrest}{end}\n             traded {trade} | unsold in warehouse: {waiting}")


def _clamp_sales(state, trade):
    for good, lots in trade.items():
        if lots < 0:
            trade[good] = max(lots, -(getattr(state, good) // LOT))
    return trade


def play(lands, books=None, rules=None, price_log=None, needs=NO_NEEDS, reacts=False, stone_hands=2):
    """@brief Play MONTHS months. lands = [(name, config)]; books None = no market.
    @param reacts True: a realm moves its extra hands off a good whose price is
           below the start price."""
    realms = [Realm(name, config, seed) for seed, (name, config) in enumerate(lands)]
    for _ in range(MONTHS):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        if books is not None:
            prices = {g: (buy_price(b, rules), sell_price(b, rules)) for g, b in books.items()}
            if price_log is not None:
                price_log.append({g: (*prices[g], books[g].stock()) for g in GOODS})
            requests = {r.name: _clamp_sales(r.state, trade_requests(r.state, r.config, prices, needs)) for r in live}
            fills, paid = resolve_market(books, rules, requests)
            for r in live:
                r.apply(fills[r.name], prices, paid.get(r.name, 0))
            spoil(books, rules)
        low_price = {}
        if books is not None and reacts:
            low_price = {g: b.price < b.start_price for g, b in books.items()}
        for r in live:
            month_config, cold_pct, worn_pct = consume_needs(r.state, r.config, needs)
            r.cold_months += cold_pct > 0
            r.worn_months += worn_pct > 0
            r.state = resolve_turn(r.state, month_orders(r.state, r.config, low_price, stone_hands), month_config).state
            r.lowest_food = min(r.lowest_food, r.state.food)
            r.reduced_months += r.state.ration == "reduced"
    return realms


def lands_of(base, granary, forest, quarry):
    return [("granary", realm_config(base, granary)), ("forest", realm_config(base, forest)),
            ("quarry", realm_config(base, quarry))]


def print_prices(price_log):
    for month, row in enumerate(price_log, start=1):
        if month % 3 and month != 1:
            continue
        cells = "  ".join(f"{g} {row[g][0]:>2}/{row[g][1]:<2} ({row[g][2]:>4})" for g in GOODS)
        print(f"    month {month:>2}: {cells}")


def main():
    base = load_config()
    mild = lands_of(base, {"food": 18, "wood": 4, "stone": 3}, {"food": 14, "wood": 9, "stone": 3},
                    {"food": 14, "wood": 4, "stone": 6})
    strong = lands_of(base, {"food": 18, "wood": 4, "stone": 3}, {"food": 12, "wood": 9, "stone": 3},
                      {"food": 12, "wood": 4, "stone": 6})
    light = lands_of(base, {"food": 17, "wood": 4, "stone": 3}, {"food": 15, "wood": 9, "stone": 3},
                     {"food": 15, "wood": 4, "stone": 6})
    needs = Needs()
    print("== light lands with firewood and stone upkeep, without market (each realm alone)")
    for name, config in light:
        print(f"  {name:<8} {play([(name, config)], needs=needs)[0].summary(None)}")
    # Earlier runs (old price rule, no start stock; numbers in PLAN.md): the
    # first two rows repeat them as a reference.
    old_rule = Rules(price_rule="unsold")
    with_stock = Rules(start_stock=START_STOCK)
    variants = {
        "A+B, old price rule, no start stock, no reaction": (light, old_rule, needs),
        "A+B, old price rule, no start stock, realms react": (light, old_rule, needs, True),
        "A+B, new price rule, no start stock, realms react": (light, Rules(), needs, True),
        "A+B, new price rule, start stock, realms react": (light, with_stock, needs, True),
        "A+B, new price rule, start stock, no reaction": (light, with_stock, needs),
        "A+B, new price rule, start stock, margin 25, realms react":
            (light, Rules(margin_pct=25, start_stock=START_STOCK), needs, True),
        "mild lands (granary 18, others 14), new rule, start stock, react": (mild, with_stock, needs, True),
    }
    for label, (lands, rules, variant_needs, *react) in variants.items():
        print(f"\n== {label}")
        books, price_log = new_books(rules), []
        for realm in play(lands, books, rules, price_log, variant_needs, bool(react)):
            print(f"  {realm.name:<8} {realm.summary(books)}")
        print(f"  prices buy/sell per lot of {LOT} (warehouse stock):")
        print_prices(price_log)


# Three levels per resource (2026-11-08): poor yields less than the realm
# needs, fair about what it needs, rich more. Food has narrower levels: a
# realm poor in food fell even with the market (strong lands above).
LEVEL_YIELD = {
    "food": {"poor": 14, "fair": 15, "rich": 17},
    "wood": {"poor": 4, "fair": 6, "rich": 9},
    "stone": {"poor": 3, "fair": 4, "rich": 6},
}
LEVEL_MARK = {"poor": "-", "fair": "=", "rich": "+"}
# "Zero sum": every realm has one rich, one fair and one poor resource, in
# any order (6 profiles), or everything fair (the other 2 of 8).
PROFILES = [
    ("rich", "fair", "poor"), ("rich", "poor", "fair"), ("fair", "rich", "poor"),
    ("poor", "rich", "fair"), ("fair", "poor", "rich"), ("poor", "fair", "rich"),
    ("fair", "fair", "fair"), ("fair", "fair", "fair"),
]
START_STOCK_EIGHT = {"food": 800, "wood": 400, "stone": 250}  # about 8/3 of the three-realm stock


def eight_lands(base, level_yield=LEVEL_YIELD):
    """@brief One config per profile, named by its levels, e.g. "F+ W= S-"."""
    lands = []
    for index, levels in enumerate(PROFILES):
        yields = {good: level_yield[good][level] for good, level in zip(GOODS, levels)}
        marks = " ".join(f"{good[0].upper()}{LEVEL_MARK[level]}" for good, level in zip(GOODS, levels))
        lands.append((f"{index + 1} {marks}", realm_config(base, yields)))
    return lands


def print_totals(realms):
    """@brief The margin that left the game and the goods that changed hands."""
    spent = sum(r.spent for r in realms)
    earned = sum(r.earned for r in realms)
    moved = " ".join(f"{g} {sum(r.bought[g] for r in realms)}" for g in GOODS)
    fallen = [r.name for r in realms if r.state.game_over]
    print(f"  bought in all: {moved} | gold paid {spent}, to sellers {earned}, margin and start stock {spent - earned}"
          f" | fallen: {fallen or 'none'}")


def _levels(wood, stone, food=(14, 15, 17)):
    """@brief LEVEL_YIELD with other levels (poor, fair, rich)."""
    return {"food": dict(zip(("poor", "fair", "rich"), food)),
            "wood": dict(zip(("poor", "fair", "rich"), wood)),
            "stone": dict(zip(("poor", "fair", "rich"), stone))}


def main_eight():
    base = load_config()
    needs = Needs()
    long_winter = Needs(firewood_months=(0, 1, 2, 10, 11))  # November to March
    first = Rules(start_stock=START_STOCK_EIGHT)
    stock_out = Rules(start_stock=START_STOCK_EIGHT, start_stock_in_price=False)
    poorer = _levels((3, 6, 9), (2, 4, 6))
    poorer_rich8 = _levels((3, 6, 8), (2, 4, 6))
    # Second tuning (2026-11-08) on the best run so far: poorer levels,
    # firewood November to March, start stock out of the price rule.
    heavy_upkeep = Needs(firewood_months=(0, 1, 2, 10, 11), stone_buildings=1)
    food16 = _levels((3, 6, 9), (2, 4, 6), food=(14, 15, 16))
    # Third tuning (2026-11-08): food 14/15/16 kept; stone upkeep between
    # 1 per 2 buildings and 1 per building.
    two_thirds = Needs(firewood_months=(0, 1, 2, 10, 11), stone_per=2, stone_buildings=3)
    candidates = {
        "stone upkeep 2 per 3 buildings, 2 stone hands": (two_thirds, 2),
        "stone upkeep 1 per building, 3 stone hands": (heavy_upkeep, 3),
    }
    for label, (variant_needs, hands) in candidates.items():
        print(f"== {label}, food 14/15/16, each alone (no market)")
        for name, config in eight_lands(base, food16):
            alone = play([(name, config)], needs=variant_needs, stone_hands=hands)[0]
            print(f"  {name:<12} {alone.summary(None)}")
    # All realms react to prices. The first row repeats the chosen run in PLAN.md.
    variants = {
        "food 14/15/16, stone upkeep 1 per 2 buildings, 2 stone hands": (stock_out, food16, long_winter, 2),
        "food 14/15/16, stone upkeep 2 per 3 buildings, 2 stone hands": (stock_out, food16, two_thirds, 2),
        "food 14/15/16, stone upkeep 1 per building, 3 stone hands": (stock_out, food16, heavy_upkeep, 3),
    }
    for label, (rules, level_yield, variant_needs, hands) in variants.items():
        print(f"\n== {label}")
        books, price_log = new_books(rules), []
        realms = play(eight_lands(base, level_yield), books, rules, price_log, variant_needs, True, hands)
        for realm in realms:
            print(f"  {realm.name:<12} {realm.summary(books)}")
        print_totals(realms)
        print(f"  prices buy/sell per lot of {LOT} (warehouse stock):")
        print_prices(price_log)


if __name__ == "__main__":
    if sys.argv[1:] == ["eight"]:
        main_eight()
    else:
        main()
