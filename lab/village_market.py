"""@brief Village lab, block A: the market as a building, merchants with
their own mood (docs/DESIGN.md, "The market as a building, merchants and
their mood"). Finds the values before the engine gets them.

Usage: docker compose run --rm -T tests python lab/village_market.py [base|why|cost|gold|timing|capacity|tax|mood|all]

Built on the real engine: the market, the needs, the land levels and the
eight sites are those of engine/config.toml (resolve_month runs every
month). On top, this script applies the rules of block A that the engine
does not have yet:
- the market building: a config entry and a zone purpose added at run time
  (center zone); until it is active the realm cannot trade;
- merchants: adults kept off the fields while the market is active, up to
  its jobs; they cap the lots a realm can trade in a month;
- the merchants' tax: their own rate on the gold value of the month's
  trades; the merchants no longer pay the ordinary tax;
- the merchants' mood: the engine's shared factors (no granary reserve),
  plus a trade factor, with a slower approach; their own unrest ladder,
  which stops at the strike (no trade the next month).

Every realm plays the same fixed policy, so the differences come from the
land and from when the market opens:
- trade: buy food up to 2 months, sell food above 2 months (3 from August
  to December); wood and stone kept for 4 months of needs plus the next
  building, bought below, sold above. Buys first, then sells, within the
  merchants' lots;
- workers: 4 on wood, 3 on stone (twice on a rich resource once the market
  is open, if 2 months of food are stored), merchants, the rest on the fields;
- gold: taxes down to 5 % above 150 gold, back to 10 % below 80, a feast
  of 80 gold a season above 200;
- building: the market first (when the policy's month comes and wood and
  stone allow it), then a farm, else a house when housing runs short.

Limits, on purpose:
- The engine's mood is still one number for everyone; the merchants' mood
  is computed here on the side and does not feed back into the peasants'.
- A fixed policy is not a council: it shows costs, flows and edges.
- No claims of new land.
"""

import copy
import dataclasses
import sys

from engine import load_config, new_game
from engine import territory
from engine.config import BuildingConfig
from engine.market import GOODS, RealmMonth, buy_price, new_market, sell_price, stock
from engine.market import resolve_month
from engine.orders import BuildOrder, parse_order
from engine.turn import firewood_needed, food_needed, housing_capacity, jobs_in_sector, mood_factors, stone_upkeep

MONTHS = 24
REALMS = 8
SALARY = 6
BEFORE_WINTER = (8, 9, 10, 11, 12)  # month of the year, August to December
BASE_HANDS = {"wood": 4, "stone": 3}
KEEP_GOLD = 20
# Zone purposes the market may stand in. The spec (2026-11-08) wants a
# reserved market zone; the palace's reserve east of the square stands in for it.
# First run: ("center", "houses"); with "center" only, houses filled it first.
MARKET_PURPOSES = [("reserve",)]


@dataclasses.dataclass(frozen=True)
class Rules:
    """@brief The values of block A under test."""
    market_wood: int = 80  # lab 2026-11-08: with 40-60 stone 5-7 realms of 8 fell
    market_stone: int = 0
    market_gold: int = 0
    build_turns: int = 2
    jobs: int = 6
    lots_per_merchant: int = 2
    # The merchants' own tax (decided 2026-11-08), on the gold value of the
    # month's trades; they no longer pay the ordinary tax.
    merchant_tax_pct: int = 10
    merchant_tax_free: int = 5  # like the peasants' tax_free_rate
    merchant_tax_per_point: int = -10
    shock_pct: int = 50  # famine and cold shocks on the merchants (deaths in full)
    # Merchants' mood (per mille, like the engine's)
    approach_pct: int = 10  # peasants: 25; merchants remember longer
    busy_bonus: int = 100  # recent use of the capacity at least busy_use_pct
    busy_use_pct: int = 40
    idle_malus: int = -250  # no lot traded in the recent months (first run: -150)
    recent_months: int = 3
    effort_loss_pct: int = 50  # capacity lost by discontented merchants
    strike_months: int = 1  # months without trade after the ladder reaches the strike
    # Diagnosis switches: which part of block A costs the realms
    merchants_off_fields: bool = True  # False: the merchants cost no farmer
    capped: bool = True  # False: no lot cap


@dataclasses.dataclass
class Policy:
    """@brief When a realm opens its market (month of the game, 0 = never)."""
    open_from: int = 1
    stop_trade: tuple[int, int] = (0, 0)  # months with no trade asked (the mood test)
    free_market: bool = False  # the old rule: market open from month 1, no building, no cap


@dataclasses.dataclass
class Merchants:
    """@brief The merchants' class, kept by the lab beside the engine state."""
    mood: int = 500
    low_mood_turns: int = 0
    unrest: str = "calm"
    strike_left: int = 0
    used: list = dataclasses.field(default_factory=list)  # lots traded / capacity, per month


class Realm:
    """@brief One realm: engine state plus block A's numbers."""

    def __init__(self, key, config, seed, site, policy):
        self.key, self.policy = key, policy
        self.state = new_game(config, seed, site)
        self.state.council_salary = SALARY
        self.name = f"{key} " + " ".join(f"{g[0].upper()}{_mark(self.state.land_levels[g])}" for g in GOODS)
        self.merchants = Merchants()
        self.opened = 0  # month the market became active
        self.tax_earned, self.lots_traded, self.lots_wanted, self.lots_cut = 0, 0, 0, 0
        self.max_lots = 0
        self.lots_filled, self.value_traded = 0, 0  # what the warehouse really gave or took
        self.lowest_food, self.reduced_months, self.cold_months = self.state.food, 0, 0
        self.strike_months, self.protest_months = 0, 0
        self.merchant_low = 1000


def _mark(level):
    return {"poor": "-", "fair": "=", "rich": "+"}[level]


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, (raw, code, message)
    return order


def lab_config(rules):
    """@brief The engine config with a market building (center zone)."""
    base = load_config()
    market = BuildingConfig(wood=rules.market_wood, stone=rules.market_stone, gold=rules.market_gold,
                            build_turns=rules.build_turns, jobs=0, output_per_worker=0, sector="",
                            housing=0, hex_steps=[["E"]])
    # Why jobs=0 in the engine: the merchants are kept by this script; the
    # engine sees them as idle adults.
    # Center or houses: with "center" only, houses filled the center first
    # and two realms never found room for the market (first run).
    territory.KIND_PURPOSES["market"] = MARKET_PURPOSES[0]
    return dataclasses.replace(base, buildings={**base.buildings, "market": market})


# ---- the market building and the merchants ---------------------------------

def market_active(state):
    # Baselines with the old rule mark their state; deepcopy in the engine
    # keeps the extra attribute from month to month.
    if getattr(state, "lab_free_market", False):
        return True
    return any(b.kind == "market" and b.turns_left == 0 for b in state.buildings)


def market_started(state):
    return any(b.kind == "market" for b in state.buildings)


def merchant_count(realm, rules):
    if realm.policy.free_market or not market_active(realm.state):
        return 0
    return min(rules.jobs, realm.state.adults // 10)


def capacity(realm, rules):
    """@brief Lots the merchants can trade this month (0 during a strike)."""
    m = realm.merchants
    if realm.policy.free_market or not rules.capped:
        return 999
    if m.strike_left:
        return 0
    lots = merchant_count(realm, rules) * rules.lots_per_merchant
    if m.mood < load_config().people.discontent_below:
        lots = lots * (100 - rules.effort_loss_pct) // 100
    return lots


# ---- policy -----------------------------------------------------------------

def months_of_food(state, config):
    normal = copy.deepcopy(state)
    normal.ration = "normal"
    return state.food / max(1, food_needed(normal, config))


def next_building(state, config, policy):
    if not market_started(state) and policy.open_from and state.turn >= policy.open_from:
        if territory.find_place(state, config, "market"):
            return "market"
    if territory.find_place(state, config, "farm"):
        return "farm"
    if housing_capacity(state, config) - state.population() < 10 and territory.find_place(state, config, "house"):
        return "house"
    return None


def stock_targets(state, config, policy):
    """@brief Wood and stone to hold: 4 months of needs plus the next building."""
    ahead = copy.deepcopy(state)
    wood = 0
    for _ in range(4):
        wood += firewood_needed(ahead, config)
        ahead.turn += 1
    stone = 4 * stone_upkeep(state, config)
    kind = next_building(state, config, policy)
    if kind:
        wood += config.buildings[kind].wood
        stone += config.buildings[kind].stone
    return {"wood": wood, "stone": stone}


def wanted_trades(state, config, market, policy):
    """@brief {good: lots}, > 0 buy, < 0 sell, before the capacity cap."""
    lot = config.market.lot_units
    trade = {}
    need = food_needed(state, config)
    if months_of_food(state, config) < 2:
        # Up to 2 months: the ration rule goes back to normal only above 1.5,
        # so buying up to 1.5 kept the poor lands on the reduced ration.
        trade["food"] = _affordable(-(-(2 * need - state.food) // lot), buy_price(market, config, "food"), state.gold)
    month = (state.turn - 1) % 12 + 1
    keep_food = (3 if month in BEFORE_WINTER else 2) * need
    if state.food - keep_food >= lot:
        trade["food"] = -((state.food - keep_food) // lot)
    for good, target in stock_targets(state, config, policy).items():
        have = getattr(state, good)
        if have < target:
            trade[good] = _affordable(-(-(target - have) // lot), buy_price(market, config, good), state.gold)
        elif have - (target + lot) >= lot:
            trade[good] = -((have - target - lot) // lot)
    # A Treasurer sees the warehouse: no more lots asked than it holds (the
    # first run asked blindly and spent the merchants' lots on empty shelves).
    for good, lots in trade.items():
        if lots > 0:
            trade[good] = min(lots, -(-stock(market.goods[good]) // lot))
    return {g: n for g, n in trade.items() if n}


def _affordable(lots, price, gold):
    return max(0, min(lots, (gold - KEEP_GOLD) // max(price, 1)))


def cap_trades(trade, lots_left):
    """@brief Buys first (needs), then sells, within the merchants' lots."""
    capped = {}
    for good, lots in sorted(trade.items(), key=lambda item: item[1] < 0):
        take = min(abs(lots), lots_left)
        if take:
            capped[good] = take if lots > 0 else -take
            lots_left -= take
    return capped


def month_orders(realm, config, market, rules):
    """@brief This month's orders, trades included; also counts the lots."""
    state, orders = realm.state, []
    stop_from, stop_to = realm.policy.stop_trade
    can_trade = market_active(state) and not (stop_from <= state.turn <= stop_to)
    if can_trade:
        wanted = wanted_trades(state, config, market, realm.policy)
        lots_left = capacity(realm, rules)
        capped = cap_trades(wanted, lots_left)
        realm.lots_wanted += sum(abs(n) for n in wanted.values())
        realm.lots_cut += sum(abs(n) for n in wanted.values()) - sum(abs(n) for n in capped.values())
        _note_use(realm, sum(abs(n) for n in capped.values()), lots_left)
        for good, lots in capped.items():
            side = "buy" if lots > 0 else "sell"
            orders.append(_order({"action": "trade", "good": good, "side": side, "lots": abs(lots)}))
    elif market_active(state):
        _note_use(realm, 0, capacity(realm, rules))
    orders += ration_orders(state, config)
    orders += gold_orders(state)
    orders.append(worker_order(realm, config, rules))
    orders += build_orders(state, config, realm.policy)
    return orders


def _note_use(realm, lots, cap):
    realm.lots_traded += lots
    realm.max_lots = max(realm.max_lots, lots)
    realm.merchants.used.append((lots, cap))


def ration_orders(state, config):
    months = months_of_food(state, config)
    if state.ration == "normal" and months < 1:
        return [_order({"action": "set_ration", "ration": "reduced"})]
    if state.ration == "reduced" and months > 1.5:
        return [_order({"action": "set_ration", "ration": "normal"})]
    return []


def gold_orders(state):
    """@brief A sensible sovereign spends idle gold on the people: taxes down
    to the free rate when the treasury is full, a feast a season when richer.
    Without it every baseline revolts by month 20 with 300-400 gold unused."""
    orders = []
    if state.gold > 150 and state.tax_rate > 5:
        orders.append(_order({"action": "set_tax", "rate": 5}))
    if state.gold < 80 and state.tax_rate < 10:
        orders.append(_order({"action": "set_tax", "rate": 10}))
    if state.gold > 200 and state.turn % 3 == 0:
        orders.append(_order({"action": "hold_feast", "gold": 80}))
    return orders


def worker_order(realm, config, rules):
    state = realm.state
    hands = {}
    for good in ("wood", "stone"):
        base = BASE_HANDS[good]
        if market_active(state) and state.land_levels.get(good) == "rich" and months_of_food(state, config) >= 2:
            base *= 2  # a rich land sells its surplus once it has a market
        hands[good] = min(base, jobs_in_sector(state, config, good))
    merchants = merchant_count(realm, rules) if rules.merchants_off_fields else 0
    food = min(jobs_in_sector(state, config, "food"), state.adults - hands["wood"] - hands["stone"] - merchants)
    return _order({"action": "assign_workers", "food": max(0, food), **hands})


def build_orders(state, config, policy):
    kind = next_building(state, config, policy)
    if not kind:
        return []
    spec = config.buildings[kind]
    reserve_wood = firewood_needed(state, config) * 2  # do not build with the firewood
    if state.wood - reserve_wood >= spec.wood and state.stone >= spec.stone and state.gold >= spec.gold:
        if kind == "market":
            # Why model_construct: the order catalog does not list the market yet.
            return [BuildOrder.model_construct(action="build", building="market", priority=0, zone=None, x=None, y=None)]
        return [_order({"action": "build", "building": kind})]
    return []


# ---- after the month: tax and the merchants' mood --------------------------

def merchant_tax(events, market_before, rules):
    """@brief The merchants' tax: their rate on the gold value of this month's
    trades (lots bought and lots put on sale, at the month's mid price)."""
    value = 0
    for event in events:
        if event.kind in ("trade_bought", "trade_on_sale"):
            value += event.data["lots"] * market_before.goods[event.data["good"]].price
    return value * rules.merchant_tax_pct // 100


def ordinary_tax_on_merchants(adults, merchants, tax_rate, config):
    """@brief The part of the engine's ordinary tax that the merchants paid
    (the engine taxes every adult); the lab gives it back."""
    divisor = config.economy.tax_divisor
    return adults * tax_rate // divisor - (adults - merchants) * tax_rate // divisor


def _event_value(events, kind, key):
    return sum(e.data.get(key, 0) for e in events if e.kind == kind)


def update_merchants(realm, config, rules, events):
    """@brief The merchants' month: target, inertia, shocks, ladder.
    Uses the engine's shared factors (minus the granary reserve) and the
    same shocks (famine, deaths, cold), plus the trade factor."""
    m, state = realm.merchants, realm.state
    if not market_active(state):
        return
    missing_pct = _event_value(events, "famine", "missing_pct")
    deaths = _event_value(events, "demography", "deaths")
    factors = mood_factors(state, config, food_needed(state, config), missing_pct, deaths)
    factors.pop("reserve")
    factors["taxes"] = max(0, rules.merchant_tax_pct - rules.merchant_tax_free) * rules.merchant_tax_per_point
    factors["trade"] = trade_factor(m, rules)
    target = max(0, min(1000, config.mood.base + sum(factors.values())))
    m.mood += (target - m.mood) * rules.approach_pct // 100
    m.mood -= missing_pct * config.mood.famine_shock_per_missing_pct * rules.shock_pct // 100
    m.mood -= deaths * config.mood.death_shock
    needed = _event_value(events, "firewood_short", "needed")
    if needed:
        cold_pct = _event_value(events, "firewood_short", "missing") * 100 // needed
        m.mood -= cold_pct * config.needs.cold_shock_per_pct * rules.shock_pct // 100
    m.mood = max(0, min(1000, m.mood))
    update_ladder(realm, config, rules)


def trade_factor(m, rules):
    recent = m.used[-rules.recent_months:]
    lots = sum(n for n, _ in recent)
    cap = sum(c for _, c in recent)
    if lots == 0:
        return rules.idle_malus
    if cap and lots * 100 // cap >= rules.busy_use_pct:
        return rules.busy_bonus
    return 0


def update_ladder(realm, config, rules):
    """@brief The peasants' ladder, stopped at the strike."""
    m, unrest = realm.merchants, config.unrest
    if m.strike_left:
        m.strike_left -= 1
    m.low_mood_turns = m.low_mood_turns + 1 if m.mood < unrest.threshold else max(0, m.low_mood_turns - 1)
    if m.low_mood_turns >= unrest.strike_turns:
        if m.unrest != "strike":
            m.strike_left = rules.strike_months
        m.unrest = "strike"
    elif m.low_mood_turns >= unrest.protest_turns:
        m.unrest = "protests"
    else:
        m.unrest = "calm"
    realm.strike_months += m.unrest == "strike"
    realm.protest_months += m.unrest == "protests"
    realm.merchant_low = min(realm.merchant_low, m.mood)


# ---- the game ----------------------------------------------------------------

CONFIG = [None]  # the config of the running game, for the report


def play(rules, policies, label):
    config = lab_config(rules)
    CONFIG[0] = config
    realms = [Realm(str(i + 1), config, i, i, policies[i]) for i in range(REALMS)]
    market = new_market(config, REALMS)
    for r in realms:
        r.state.lab_free_market = r.policy.free_market
    price_log = []
    for _ in range(MONTHS):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        price_log.append({g: (buy_price(market, config, g), stock(market.goods[g])) for g in GOODS})
        months = {r.key: RealmMonth(r.state, month_orders(r, config, market, rules)) for r in live}
        before = market
        taxed = {r.key: (r.state.adults, merchant_count(r, rules), r.state.tax_rate) for r in live}
        market, results = resolve_month(market, months, config)
        for r in live:
            result = results[r.key]
            r.state = result.state
            tax = merchant_tax(result.events, before, rules)
            for event in result.events:
                if event.kind in ("trade_bought", "trade_on_sale"):
                    r.lots_filled += event.data["lots"]
                    r.value_traded += event.data["lots"] * before.goods[event.data["good"]].price
            r.state.gold += tax - ordinary_tax_on_merchants(*taxed[r.key], config)
            r.tax_earned += tax
            if market_active(r.state) and not r.opened:
                r.opened = r.state.turn - 1
            update_merchants(r, config, rules, result.events)
            r.lowest_food = min(r.lowest_food, r.state.food)
            r.reduced_months += r.state.ration == "reduced"
            r.cold_months += any(e.kind == "firewood_short" for e in result.events)
    report(label, realms, price_log)
    return realms


def report(label, realms, price_log):
    print(f"\n== {label}")
    for r in realms:
        s, m = r.state, r.merchants
        end = f" | {s.game_over} at {s.turn - 1}" if s.game_over else ""
        print(f"  {r.name:<11} open {r.opened or '-':>2} | gold {s.gold:>4} mtax {r.tax_earned:>3}"
              f" | lots asked {r.lots_traded:>3} filled {r.lots_filled:>3} value {r.value_traded:>4}"
              f" (max/month {r.max_lots:>2}, cut {r.lots_cut:>3} of {r.lots_wanted:>3})"
              f" | food low {r.lowest_food:>5} reduced {r.reduced_months:>2} cold {r.cold_months}"
              f" | pop {s.population():>3}/{housing_capacity(s, CONFIG[0]):>3} farms {sum(b.kind == 'farm' for b in s.buildings)}"
              f" mood {s.mood:>3} {s.unrest}"
              f" | merchants {m.mood:>3} (low {r.merchant_low if r.opened else '-':>3}) {m.unrest}"
              f" protests {r.protest_months} strike {r.strike_months}{end}")
    fallen = sum(1 for r in realms if r.state.game_over)
    opened = [r.opened for r in realms if r.opened]
    print(f"  ALL: fallen {fallen} | opened {len(opened)} (months {sorted(opened)}) | lots asked {sum(r.lots_traded for r in realms)}"
          f" filled {sum(r.lots_filled for r in realms)} value {sum(r.value_traded for r in realms)}"
          f" cut {sum(r.lots_cut for r in realms)} | tax {sum(r.tax_earned for r in realms)}"
          f" | gold {sum(r.state.gold for r in realms)} | merchants' strike months {sum(r.strike_months for r in realms)}")
    for month in (1, 6, 12, 18, 24):
        if month <= len(price_log):
            row = price_log[month - 1]
            print(f"    month {month:>2}: " + "  ".join(f"{g} {row[g][0]:>2} ({row[g][1]:>4})" for g in GOODS))


def same(policy):
    return [dataclasses.replace(policy) for _ in range(REALMS)]


def main_base():
    """@brief Baselines for the same policy: no market at all, and the old rule
    (market open from month 1, no building, no cap, no tax)."""
    play(Rules(), same(Policy(open_from=0)), "base: no market at all")
    play(Rules(merchant_tax_pct=0), same(Policy(open_from=0, free_market=True)), "base: old rule, market open from month 1")


def main_why():
    """@brief Which part of block A makes realms fall (cost 60/40, 2 months)."""
    cheap = dict(market_wood=60, market_stone=40)
    play(Rules(**cheap, merchants_off_fields=False, capped=False), same(Policy()), "why: building only (no farmer lost, no cap)")
    play(Rules(**cheap, capped=False), same(Policy()), "why: building + merchants off the fields, no cap")
    play(Rules(**cheap, merchants_off_fields=False), same(Policy()), "why: building + cap, no farmer lost")
    free = dict(merchants_off_fields=False, capped=False)
    play(Rules(market_wood=0, market_stone=0, build_turns=1, **free), same(Policy()), "why: a free market of 1 month (timing only)")
    play(Rules(market_wood=80, market_stone=0, **free), same(Policy()), "why: building of 80 wood, no stone")


def main_cost():
    """@brief Building cost and months: can every land open before the second winter?"""
    # First run (60/40 to 150/100 with stone): 5-7 realms of 8 fell, the stone
    # price at the cap; the market took the stone of the houses.
    for wood, stone, turns in ((60, 0, 2), (80, 0, 2), (80, 10, 2), (120, 0, 3)):
        play(Rules(market_wood=wood, market_stone=stone, build_turns=turns), same(Policy(open_from=1)),
             f"cost {wood} wood {stone} stone, {turns} months, everyone as soon as possible")


def main_gold():
    """@brief Part of the cost in gold: realms poor in wood opened last (month 9)
    and fell in the second winter; gold does not depend on the land."""
    for wood, gold in ((80, 0), (50, 50), (40, 80), (30, 100)):
        play(Rules(market_wood=wood, market_gold=gold), same(Policy()), f"cost {wood} wood {gold} gold, 2 months")


def main_timing():
    """@brief First to open: realms open at months 1, 4, 7, 13; two never."""
    opens = [1, 4, 7, 13, 1, 4, 0, 0]
    play(Rules(), [Policy(open_from=o) for o in opens], f"timing, open from {opens} (0 = never)")


def main_capacity():
    for jobs, per in ((6, 1), (6, 2), (6, 3), (4, 3)):
        play(Rules(jobs=jobs, lots_per_merchant=per), same(Policy(open_from=1)),
             f"capacity, {jobs} jobs x {per} lots")


def main_tax():
    """@brief The merchants' tax on the value of the month's trades.
    First run: a share of the margin, 0.4 gold a realm a month at 50 %."""
    for rate in (0, 5, 10, 20, 30):
        play(Rules(merchant_tax_pct=rate), same(Policy(open_from=1)), f"merchants' tax {rate} % of the trades' value")


def main_mood():
    """@brief Realms 1-4 stop trading in months 12-18: do the merchants strike,
    and only there?"""
    policies = [Policy(open_from=1, stop_trade=(12, 18)) for _ in range(4)] + [Policy(open_from=1) for _ in range(4)]
    play(Rules(idle_malus=-150, shock_pct=100), policies, "mood, first run's values (idle -150, shocks in full), realms 1-4 idle 12-18")
    play(Rules(idle_malus=-250, shock_pct=100), policies, "mood, idle -250, shocks in full, realms 1-4 idle 12-18")
    play(Rules(), policies, "mood, idle -250, shocks at half, realms 1-4 idle 12-18")


if __name__ == "__main__":
    runs = {"base": main_base, "why": main_why, "cost": main_cost, "gold": main_gold, "timing": main_timing, "capacity": main_capacity, "tax": main_tax, "mood": main_mood}
    chosen = sys.argv[1:] or ["all"]
    for name, run in runs.items():
        if "all" in chosen or name in chosen:
            run()
