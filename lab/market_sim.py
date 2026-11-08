"""@brief Market lab: three scripted realms trade with one outside merchant.

Usage: docker compose run --rm -T tests python lab/market_sim.py

Three realms (seeds 0, 1, 2: three sites of the same world, the same core)
play 24 months on the real engine, each with a fixed policy:
- farmer: everyone it can on the fields, builds farms, sells the food above
  a reserve of 2 months, buys the wood a farm needs;
- builder: builds houses while housing runs short, buys the wood and stone
  they need, buys food instead of cutting the ration;
- prudent: tax 12, keeps gold, buys food when the reserve is short (winter),
  sells the wood and stone above a small stock.

The market (docs/DESIGN.md, "Economy and trade", proposal 2026-11-08):
- one merchant outside the realms, with a stock of food, wood and stone;
- the price of a lot of 10 units comes from the stock at the start of the
  month: base_price * base_stock / stock, kept within min_pct..max_pct of the
  base. Selling to the merchant raises its stock (price falls), buying
  lowers it (price rises), for everybody;
- buying costs price + margin, selling pays price - margin;
- every month the stock moves restock_pct of the way back to base_stock
  (the outside world supplies or absorbs goods);
- orders are filled together at the month's price: sales first (always
  accepted), then purchases; when the stock is short, it is split in
  proportion to the lots asked, so the order of the realms does not matter.

Limits, on purpose:
- The market is applied by this script before each resolve_turn, by
  changing the realm's food, wood, stone and gold. It is not an engine
  order: no validator, no events, no replay.
- A fixed policy is not a council: it shows prices, flows and edges, not
  what a sensible counsellor would do.
- No claims of new land: every realm stays in its core (room for 2 more
  farms and about 18 houses).

Each policy is also played alone without the market, so the effect of
trading can be read against the same policy.
"""

import copy
import dataclasses

from engine import load_config, new_game, parse_order, resolve_turn
from engine.territory import find_place
from engine.turn import food_needed, housing_capacity, jobs_in_sector

MONTHS = 24
WINTER = (0, 1, 2, 11)  # month index (0 = January)
SALARY = 6  # a council of three after the halving, as in territory_balance.py
LOT = 50  # units per lot; prices are gold per lot (at 10 units a lot, 2 gold with a 10 % margin rounded to 2/1)
GOODS = ("food", "wood", "stone")


@dataclasses.dataclass
class GoodMarket:
    """@brief The merchant's side of one good. All values are integers."""
    base_price: int  # gold per lot when stock == base_stock
    base_stock: int  # units
    stock: int  # units, now


@dataclasses.dataclass
class MarketRules:
    margin_pct: int = 10
    min_pct: int = 50  # price floor, percent of the base price
    max_pct: int = 300  # price ceiling
    restock_pct: int = 20  # share of the gap to base_stock closed every month


def new_market(food_price=10, wood_price=15, stone_price=20, food_stock=600, wood_stock=200, stone_stock=150):
    """@brief Starting market, prices per lot of 50. Default prices from the
    labour behind them: a worker-month makes 15 food, 6 wood or 4 stone, so
    50 units are worth about 3.3, 8 and 12.5 worker-months; gold comes in at
    about 12 a month beyond upkeep and salaries."""
    return {
        "food": GoodMarket(food_price, food_stock, food_stock),
        "wood": GoodMarket(wood_price, wood_stock, wood_stock),
        "stone": GoodMarket(stone_price, stone_stock, stone_stock),
    }


def lot_price(good: GoodMarket, rules: MarketRules) -> int:
    """@brief Mid price of a lot this month, from the stock."""
    raw_price = good.base_price * good.base_stock // max(good.stock, 1)
    low = max(1, good.base_price * rules.min_pct // 100)
    high = good.base_price * rules.max_pct // 100
    return min(high, max(low, raw_price))


def buy_price(good: GoodMarket, rules: MarketRules) -> int:
    """@brief Gold per lot bought; rounded up so the margin is never zero."""
    return -(-lot_price(good, rules) * (100 + rules.margin_pct) // 100)


def sell_price(good: GoodMarket, rules: MarketRules) -> int:
    """@brief Gold per lot sold; rounded down, at least 0."""
    return lot_price(good, rules) * (100 - rules.margin_pct) // 100


def resolve_market(market, rules, requests):
    """@brief Fill one month of requests, all realms together.
    @param market {good: GoodMarket}; changed in place (stock).
    @param rules MarketRules.
    @param requests {realm: {good: lots}}, lots > 0 buy, < 0 sell. The caller
           checks that the realm owns what it sells and can pay what it buys.
    @return {realm: {good: lots filled}} with the same signs.
    """
    fills = {realm: {} for realm in requests}
    for good_name, good in market.items():
        # Sales first: the merchant always takes them.
        for realm, wanted in requests.items():
            lots = wanted.get(good_name, 0)
            if lots < 0:
                good.stock += -lots * LOT
                fills[realm][good_name] = lots
        asked = {realm: wanted.get(good_name, 0) for realm, wanted in requests.items() if wanted.get(good_name, 0) > 0}
        total = sum(asked.values())
        available = good.stock // LOT
        for realm, lots in asked.items():
            # Pro rata when short; the rounding leftover stays with the merchant.
            granted = lots if total <= available else lots * available // total
            good.stock -= granted * LOT
            fills[realm][good_name] = granted
    return fills


def restock(market, rules):
    """@brief The outside world moves every stock back towards its base."""
    for good in market.values():
        good.stock += (good.base_stock - good.stock) * rules.restock_pct // 100


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, (raw, code, message)
    return order


def _months_of_food(state, config):
    """@brief Reserve in months at the normal ration (as the steward reads it)."""
    normal = copy.deepcopy(state)
    normal.ration = "normal"
    return state.food / max(1, food_needed(normal, config))


def _steward(state, config, buys_food):
    """@brief The shared ration rule: reduced below 1 month, normal above 1.5.
    A realm that buys food on the market keeps the normal ration."""
    months = _months_of_food(state, config)
    if not buys_food and state.ration == "normal" and months < 1:
        return [_order({"action": "set_ration", "ration": "reduced"})]
    if state.ration == "reduced" and months > 1.5:
        return [_order({"action": "set_ration", "ration": "normal"})]
    return []


def _workers(state, config, wood=4, stone=2):
    food = min(jobs_in_sector(state, config, "food"), state.adults - wood - stone)
    return _order({"action": "assign_workers", "food": max(0, food), "wood": wood, "stone": stone})


def _lots_short(have, need):
    """@brief Lots to buy so that have reaches need (0 if already there)."""
    return max(0, -(-(need - have) // LOT))


def _affordable(lots, price, gold, keep):
    """@brief Lots that fit in the gold above a kept reserve."""
    return max(0, min(lots, (gold - keep) // max(price, 1)))


def farmer(state, config, prices):
    """@brief Feeds the market with food. Returns (orders, {good: lots})."""
    orders = _steward(state, config, buys_food=False) + [_workers(state, config, wood=3, stone=1)]
    trade = {}
    if prices is None:  # no market: build only with what the realm has
        prices = {good: (10 ** 6, 0) for good in GOODS}
    farm = config.buildings["farm"]
    if find_place(state, config, "farm"):
        if state.wood >= farm.wood and state.stone >= farm.stone:
            orders.append(_order({"action": "build", "building": "farm"}))
        else:
            trade["wood"] = _affordable(_lots_short(state.wood, farm.wood), prices["wood"][0], state.gold, 20)
    surplus = state.food - 2 * food_needed(state, config)
    if surplus >= LOT:
        trade["food"] = -(surplus // LOT)
    return orders, trade


def builder(state, config, prices):
    """@brief Grows the town with houses; buys what they need."""
    orders = _steward(state, config, buys_food=prices is not None) + [_workers(state, config)]
    trade = {}
    if prices is None:  # no market: the same houses, from the realm's own stock
        prices = {good: (10 ** 6, 0) for good in GOODS}
    house = config.buildings["house"]
    keep_for_house = 0
    if housing_capacity(state, config) - state.population() < 10 and find_place(state, config, "house"):
        if state.wood >= house.wood and state.stone >= house.stone and state.gold >= house.gold:
            orders.append(_order({"action": "build", "building": "house"}))
            keep_for_house = house.gold  # the market comes before the build: keep its gold
        else:
            keep = house.gold
            trade["wood"] = _affordable(_lots_short(state.wood, house.wood), prices["wood"][0], state.gold, keep)
            trade["stone"] = _affordable(_lots_short(state.stone, house.stone), prices["stone"][0], state.gold, keep)
    if _months_of_food(state, config) < 1:
        trade["food"] = _affordable(_lots_short(state.food, food_needed(state, config)), prices["food"][0], state.gold, keep_for_house)
    return orders, trade


def prudent(state, config, prices):
    """@brief Saves gold, buys food only to keep 1.5 months, sells spare wood and stone."""
    orders = _steward(state, config, buys_food=prices is not None) + [_workers(state, config)]
    if prices is None:
        prices = {good: (10 ** 6, 0) for good in GOODS}
    if state.turn == 1:
        orders.append(_order({"action": "set_tax", "rate": 12}))
    trade = {}
    if _months_of_food(state, config) < 1.5:
        target = 3 * food_needed(state, config) // 2
        trade["food"] = _affordable(_lots_short(state.food, target), prices["food"][0], state.gold, 0)
    for good, keep in (("wood", 100), ("stone", 80)):
        spare = getattr(state, good) - keep
        if spare >= LOT:
            trade[good] = -(spare // LOT)
    return orders, trade


def _apply_fills(state, fills, prices):
    """@brief Move goods and gold of the filled lots; returns the gold spent (+) or earned (-)."""
    spent = 0
    for good, lots in fills.items():
        if lots > 0:
            cost = lots * prices[good][0]
        else:
            cost = lots * prices[good][1]  # negative: gold earned
        setattr(state, good, getattr(state, good) + lots * LOT)
        state.gold -= cost
        spent += cost
    return spent


def _clamp_sales(state, trade):
    """@brief A realm cannot sell more than it owns (whole lots)."""
    for good, lots in trade.items():
        if lots < 0:
            trade[good] = max(lots, -(getattr(state, good) // LOT))
    return trade


class RealmRun:
    """@brief One realm and its running numbers."""

    def __init__(self, name, policy, config, seed):
        self.name, self.policy = name, policy
        self.state = new_game(config, seed)
        self.state.council_salary = SALARY
        self.lowest_food = self.state.food
        self.gold_spent, self.gold_earned = 0, 0
        self.reduced_months = 0
        self.bought = {good: 0 for good in GOODS}
        self.sold = {good: 0 for good in GOODS}

    def record(self, fills, spent):
        for good, lots in fills.items():
            if lots > 0:
                self.bought[good] += lots * LOT
            else:
                self.sold[good] += -lots * LOT
        if spent > 0:
            self.gold_spent += spent
        else:
            self.gold_earned += -spent

    def summary(self):
        s = self.state
        houses = sum(1 for b in s.buildings if b.kind == "house")
        farms = sum(1 for b in s.buildings if b.kind == "farm")
        trade = " ".join(f"{g} +{self.bought[g]}/-{self.sold[g]}" for g in GOODS)
        end = f" | {s.game_over} at month {s.turn - 1}" if s.game_over else ""
        return (f"gold {s.gold:>4} (spent {self.gold_spent:>4}, earned {self.gold_earned:>4}) | lowest food {self.lowest_food:>5}"
                f" | reduced {self.reduced_months:>2} m | pop {s.population():>3} | farms {farms} houses {houses:>2}"
                f" | mood {s.mood} {s.unrest} | {trade}{end}")


def play(config, policies, market=None, rules=None, price_log=None):
    """@brief Play MONTHS months for the given (name, policy) pairs.
    @param market None = no market (the policies' requests are ignored).
    @param price_log list filled with one row per month: {good: (buy, sell, stock)}.
    """
    realms = [RealmRun(name, policy, config, seed) for seed, (name, policy) in enumerate(policies)]
    for _ in range(MONTHS):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        prices = None  # no market: the policies see None and cut the ration instead of buying
        if market is not None:
            prices = {g: (buy_price(m, rules), sell_price(m, rules)) for g, m in market.items()}
            if price_log is not None:
                price_log.append({g: (*prices[g], market[g].stock) for g in GOODS})
        plans = {r.name: r.policy(r.state, config, prices) for r in live}
        if market is not None:
            requests = {r.name: _clamp_sales(r.state, plans[r.name][1]) for r in live}
            fills = resolve_market(market, rules, requests)
            for r in live:
                r.record(fills[r.name], _apply_fills(r.state, fills[r.name], prices))
            restock(market, rules)
        for r in live:
            r.state = resolve_turn(r.state, plans[r.name][0], config).state
            r.lowest_food = min(r.lowest_food, r.state.food)
            r.reduced_months += r.state.ration == "reduced"
    return realms


POLICIES = [("farmer", farmer), ("builder", builder), ("prudent", prudent)]

VARIANTS = {
    "margin 10, restock 20": (MarketRules(), {}),
    "margin 25, restock 20": (MarketRules(margin_pct=25), {}),
    "margin 10, restock 5 (prices move more)": (MarketRules(restock_pct=5), {}),
    "margin 10, small stocks (food 200)": (MarketRules(), {"food_stock": 200, "wood_stock": 80, "stone_stock": 60}),
    "margin 10, large food stock (2000)": (MarketRules(), {"food_stock": 2000}),
    "margin 10, cheap food (5 a lot)": (MarketRules(), {"food_price": 5}),
}


def print_prices(price_log):
    """@brief Buy/sell price and stock of each good every third month."""
    for month, row in enumerate(price_log, start=1):
        if month % 3 and month != 1:
            continue
        cells = "  ".join(f"{g} {row[g][0]:>2}/{row[g][1]:<2} ({row[g][2]:>4})" for g in GOODS)
        print(f"    month {month:>2}: {cells}")


def main():
    config = load_config()
    print("== without market (each policy alone)")
    for name, policy in POLICIES:
        realm = play(config, [(name, policy)])[0]
        print(f"  {name:<8} {realm.summary()}")
    for label, (rules, market_args) in VARIANTS.items():
        print(f"\n== {label}")
        price_log = []
        for realm in play(config, POLICIES, new_market(**market_args), rules, price_log):
            print(f"  {realm.name:<8} {realm.summary()}")
        print(f"  prices buy/sell per lot of {LOT} (merchant stock):")
        print_prices(price_log)


if __name__ == "__main__":
    main()
