"""@brief Village lab, block B+C stage 1: flight, the bandits' pool, raids,
the watchtower and the militia (docs/DESIGN.md, "Bandits, the watchtower,
the Gastaldo and the militia"). Finds the values before the engine gets them
and checks the spirals.

Usage: docker compose run --rm -T tests python lab/village_bandits.py [base|start|spiral|militia|all]

Built on the real engine, block A included (the market as a building,
merchants, mood per class): 8 realms on the 8 sites, resolve_month every
month. On top, after the month, this script runs the world step that the
engine does not have yet:
- flight: after FLEE_MONTHS months of deep discontent (peasants' mood below
  flee_below; merchants' below their own) a share of the class leaves:
  adults, and children with the peasants; elders stay;
- the pool: adults and children; children grow up; natural decline (more in
  winter); the bandits eat like the realms' people, from what they loot,
  and the food they lack makes the pool shrink;
- raids: the pool's adults split into parties; each party picks a realm
  (seeded generator) weighted by what lies exposed (food and wood) and by
  how weak its militia is; guards repel a party when they are enough, else
  the party carries away its loot, less the share the guards stopped;
- the watchtower: a lab building; once finished the realm may keep guards
  (the Gastaldo's militia), adults off the fields.

Every realm plays the fixed policy of lab/village_market.py (ration,
gold, trades) with the engine's market: the market first, then the
watchtower, then farms and houses; 3 merchants; guards from the policy.

Limits, on purpose:
- A fixed policy is not a council: it shows flows and edges.
- Raids take food and wood only (not goods on sale at the market, not gold).
- No doors and no acceptance (stage 2): fugitives never come back.
"""

import copy
import dataclasses
import random
import sys

from engine import load_config, new_game, territory
from engine.config import BuildingConfig
from engine.market import GOODS, RealmMonth, market_status, new_market, resolve_month, trade_capacity
from engine.orders import BuildOrder
from engine.turn import firewood_needed, food_needed, housing_capacity, jobs_in_sector
from lab.village_market import _order, cap_trades, gold_orders, ration_orders, wanted_trades, Policy

MONTHS = 24
REALMS = 8
SALARY = 6
MERCHANTS = 3
BASE_HANDS = {"wood": 6, "stone": 3}  # 4: the fair-wood realms froze in the second winter (lab)
WINTER_MONTHS = (12, 1, 2)


@dataclasses.dataclass(frozen=True)
class Rules:
    """@brief The values of block B+C under test (brackets of the spec)."""
    bandits: bool = True
    # Flight
    # First run: below 300 nobody fled before the revolt (the ladder starts at
    # 350: protests after 2 months, revolt after 6); now the protests' threshold.
    flee_below: int = 350  # peasants' mood
    merchants_flee_below: int = 350
    flee_months: int = 3  # months in a row below before anyone leaves
    flee_adult_pct: int = 2
    flee_child_pct: int = 1
    # The pool
    start_min: int = 5
    start_max: int = 15
    decline_pct: int = 5
    winter_decline_pct: int = 10
    starve_pct: int = 30  # of the share of food missing: a pool fed half loses 15 %
    # Raids
    party_size: int = 8
    carry: int = 25  # units a raider carries away
    repel_per_guard: int = 2  # raiders one guard stops
    guard_weight_pct: int = 10  # each guard makes the realm this much less attractive (max 80)
    # The watchtower
    tower_wood: int = 40
    tower_stone: int = 20
    tower_turns: int = 2


@dataclasses.dataclass
class Plan:
    """@brief One realm's choices that differ between runs."""
    tower: bool = False
    guards: int = 0
    tax: int = 0  # 0: the policy's taxes; else a fixed rate (a crisis realm)


@dataclasses.dataclass
class Pool:
    adults: int = 0
    children: int = 0
    food: int = 0
    grow_acc: int = 0
    decline_acc: int = 0


class Realm:
    def __init__(self, key, config, seed, site, plan):
        self.key, self.plan = key, plan
        self.state = new_game(config, seed, site)
        self.state.council_salary = SALARY
        self.name = f"{key} " + " ".join(f"{g[0].upper()}{_mark(self.state.land_levels[g])}" for g in GOODS)
        self.deep = {"peasants": 0, "merchants": 0}
        self.acc = {"adults": 0, "children": 0, "merchants": 0}
        self.fled_adults = self.fled_children = self.fled_merchants = 0
        self.raids = self.repelled = self.lost_food = self.lost_wood = 0
        self.tower_month = 0
        self.guards = 0
        self.peak_adults = self.state.adults
        self.lowest_mood = self.state.mood


def _mark(level):
    return {"poor": "-", "fair": "=", "rich": "+"}[level]


def lab_config(rules):
    """@brief The engine config (block A on) plus a watchtower building."""
    base = load_config()
    tower = BuildingConfig(wood=rules.tower_wood, stone=rules.tower_stone, gold=0, build_turns=rules.tower_turns,
                           jobs=0, output_per_worker=0, sector="", housing=0, hex_steps=[])
    # A lab stand-in for the reserved place near the gate: the palace's reserve.
    territory.KIND_PURPOSES["watchtower"] = ("reserve",)
    return dataclasses.replace(base, buildings={**base.buildings, "watchtower": tower})


def _has(state, kind, finished=True):
    return any(b.kind == kind and (b.turns_left == 0 or not finished) for b in state.buildings)


# ---- the policy ----------------------------------------------------------------

def _build(state, config, realm):
    """@brief Market, then the watchtower (if the plan has one), then farms and houses."""
    if not _has(state, "market", finished=False):
        kind = "market"
    elif realm.plan.tower and not _has(state, "watchtower", finished=False):
        kind = "watchtower"
    elif territory.find_place(state, config, "farm"):
        kind = "farm"
    elif housing_capacity(state, config) - state.population() < 10:
        kind = "house"
    else:
        return []
    if not territory.find_place(state, config, kind):
        return []
    spec = config.buildings[kind]
    reserve_wood = firewood_needed(state, config) * 2  # do not build with the firewood
    if state.wood - reserve_wood < spec.wood or state.stone < spec.stone or state.gold < spec.gold:
        return []
    if kind == "watchtower":  # not in the order catalogue yet
        return [BuildOrder.model_construct(action="build", building="watchtower", priority=0, zone=None, x=None, y=None)]
    return [_order({"action": "build", "building": kind})]


def month_orders(realm, config, market):
    state, orders = realm.state, []
    if market_status(state, config) == "open":
        wanted = wanted_trades(state, config, market, Policy(open_from=1))
        for good, lots in cap_trades(wanted, trade_capacity(state, config) or 0).items():
            side = "buy" if lots > 0 else "sell"
            orders.append(_order({"action": "trade", "good": good, "side": side, "lots": abs(lots)}))
    orders += ration_orders(state, config)
    if realm.plan.tax:
        if state.tax_rate != realm.plan.tax:
            orders.append(_order({"action": "set_tax", "rate": realm.plan.tax}))
    else:
        orders += gold_orders(state)
    realm.guards = min(realm.plan.guards, state.adults // 5) if _has(state, "watchtower") else 0
    merchants = min(MERCHANTS, config.buildings["market"].jobs) if _has(state, "market") else 0
    # Twice the hands on a poor resource: with 4 woodcutters the realms poor in
    # wood froze and fell even with no bandits (first run: 3 of 8).
    hands = {good: min(n * (2 if state.land_levels.get(good) == "poor" else 1), jobs_in_sector(state, config, good))
             for good, n in BASE_HANDS.items()}
    food = min(jobs_in_sector(state, config, "food"), state.adults - sum(hands.values()) - merchants - realm.guards)
    orders.append(_order({"action": "assign_workers", "food": max(0, food), **hands, "trade": merchants}))
    orders += _build(state, config, realm)
    return orders


# ---- the world step: flight, the pool, raids ------------------------------------

def _leave(realm, key, count, pct):
    """@brief Integer share with an accumulator, as births: a small realm loses someone too."""
    realm.acc[key] += count * pct
    gone, realm.acc[key] = realm.acc[key] // 100, realm.acc[key] % 100
    return min(gone, count)


def flight(realm, config, rules, pool):
    state = realm.state
    realm.deep["peasants"] = realm.deep["peasants"] + 1 if state.mood < rules.flee_below else 0
    if realm.deep["peasants"] >= rules.flee_months:
        peasants = state.adults - state.workers.trade
        adults = _leave(realm, "adults", peasants, rules.flee_adult_pct)
        children = _leave(realm, "children", state.children, rules.flee_child_pct)
        state.adults -= adults
        state.children -= children
        state.workers.food = max(0, state.workers.food - adults)
        pool.adults += adults
        pool.children += children
        realm.fled_adults += adults
        realm.fled_children += children
    merchants = state.classes.get("merchants")
    if merchants is None:
        return
    realm.deep["merchants"] = realm.deep["merchants"] + 1 if merchants.mood < rules.merchants_flee_below else 0
    if realm.deep["merchants"] >= rules.flee_months and state.workers.trade:
        gone = _leave(realm, "merchants", state.workers.trade, rules.flee_adult_pct)
        state.workers.trade -= gone
        state.adults -= gone
        pool.adults += gone
        realm.fled_merchants += gone


def _weight(realm, rules):
    exposed = realm.state.food + realm.state.wood
    return exposed * (100 - min(80, realm.guards * rules.guard_weight_pct)) // 100


def raids(live, rules, pool, rng):
    """@brief The pool's adults split into parties; each picks one realm."""
    parties = pool.adults // rules.party_size
    if rng.randrange(rules.party_size) < pool.adults % rules.party_size:
        parties += 1  # the remainder raids too, by chance
    if not parties or not live:
        return
    size = max(1, pool.adults // parties)
    weights = [max(1, _weight(r, rules)) for r in live]
    for _ in range(parties):
        realm = rng.choices(live, weights)[0]
        realm.raids += 1
        stopped = realm.guards * rules.repel_per_guard
        if stopped >= size:
            realm.repelled += 1
            continue
        loot = (size - stopped) * rules.carry
        food = min(loot, realm.state.food)
        wood = min(loot - food, realm.state.wood)
        realm.state.food -= food
        realm.state.wood -= wood
        realm.lost_food += food
        realm.lost_wood += wood
        pool.food += food


def pool_month(pool, config, rules, month_of_year):
    """@brief The bandits eat what they looted; hunger, decline, children grow up."""
    economy = config.economy
    need = pool.adults * economy.food_per_adult + pool.children * economy.food_per_child
    eaten = min(need, pool.food)
    pool.food -= eaten
    missing_pct = (need - eaten) * 100 // need if need else 0
    pct = rules.winter_decline_pct if month_of_year in WINTER_MONTHS else rules.decline_pct
    pct += missing_pct * rules.starve_pct // 100
    # An accumulator, as births: 5 % of 10 bandits is 0 rounded down (first run:
    # the pool never shrank).
    pool.decline_acc += (pool.adults + pool.children) * pct
    gone, pool.decline_acc = pool.decline_acc // 100, pool.decline_acc % 100
    from_children = min(pool.children, gone * pool.children // max(1, pool.adults + pool.children))
    pool.children -= from_children
    pool.adults = max(0, pool.adults - (gone - from_children))
    pool.grow_acc += pool.children * config.demography.child_to_adult_permille
    grown = min(pool.children, pool.grow_acc // 1000)
    pool.grow_acc %= 1000
    pool.children -= grown
    pool.adults += grown


# ---- the game ----------------------------------------------------------------------

def play(rules, plans, label, seed=0):
    config = lab_config(rules)
    rng = random.Random(seed)
    realms = [Realm(str(i + 1), config, i, i, plans[i]) for i in range(REALMS)]
    market = new_market(config, REALMS)
    pool = Pool(adults=rng.randint(rules.start_min, rules.start_max) if rules.bandits else 0)
    pool_log = []
    for month in range(MONTHS):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        months = {r.key: RealmMonth(r.state, month_orders(r, config, market)) for r in live}
        market, results = resolve_month(market, months, config)
        for r in live:
            r.state = results[r.key].state
            if _has(r.state, "watchtower") and not r.tower_month:
                r.tower_month = month + 1
        live = [r for r in realms if not r.state.game_over]
        if rules.bandits:
            for r in live:
                flight(r, config, rules, pool)
            raids(live, rules, pool, rng)
            pool_month(pool, config, rules, month % 12 + 1)
        for r in live:
            r.peak_adults = max(r.peak_adults, r.state.adults)
            r.lowest_mood = min(r.lowest_mood, r.state.mood)
        pool_log.append((pool.adults, pool.children))
    report(label, realms, pool_log)
    return realms


def report(label, realms, pool_log):
    print(f"\n== {label}")
    for r in realms:
        s = r.state
        end = f" | {s.game_over} at {s.turn - 1}" if s.game_over else ""
        print(f"  {r.name:<11} adults {s.adults:>3} (peak {r.peak_adults:>3}) | fled {r.fled_adults:>2}+{r.fled_children:>2}ch"
              f" merchants {r.fled_merchants} | raids {r.raids:>2} repelled {r.repelled:>2} lost food {r.lost_food:>4}"
              f" wood {r.lost_wood:>3} | tower {r.tower_month or '-':>2} guards {r.guards}"
              f" | food {s.food:>5} mood {s.mood:>3} (low {r.lowest_mood:>3}) {s.unrest}{end}")
    fallen = sum(1 for r in realms if r.state.game_over)
    peak = max((a for a, _ in pool_log), default=0)
    print(f"  ALL: fallen {fallen} | fled {sum(r.fled_adults + r.fled_merchants for r in realms)} adults"
          f" | raids {sum(r.raids for r in realms)} repelled {sum(r.repelled for r in realms)}"
          f" | loot food {sum(r.lost_food for r in realms)} wood {sum(r.lost_wood for r in realms)} | pool peak {peak}")
    print("    pool (adults+children) at months " + "  ".join(
        f"{m}: {pool_log[m - 1][0]}+{pool_log[m - 1][1]}" for m in (1, 6, 12, 18, 24) if m <= len(pool_log)))


def same(plan):
    return [dataclasses.replace(plan) for _ in range(REALMS)]


def main_base():
    """@brief No bandits, then bandits with no watchtower anywhere."""
    play(Rules(bandits=False), same(Plan()), "base: no bandits")
    play(Rules(), same(Plan()), "bandits, start pool 5-15, no watchtower anywhere")


def main_start():
    """@brief Does the small start pool make the first raids rare but real?"""
    for low, high in ((3, 8), (5, 15), (10, 25)):
        for seed in (0, 1):
            play(Rules(start_min=low, start_max=high), same(Plan()), f"start pool {low}-{high}, seed {seed}", seed)


def main_spiral():
    """@brief Two realms in crisis (tax 25 %): do they spiral, and do the
    others feel their bandits?"""
    crisis = [Plan(tax=25), Plan(tax=25)] + [Plan() for _ in range(6)]
    play(Rules(bandits=False), crisis, "spiral: realms 1-2 at 25 % tax, no bandits")
    play(Rules(), crisis, "spiral: realms 1-2 at 25 % tax, bandits, no watchtower")
    guarded = [Plan(tax=25), Plan(tax=25)] + [Plan(tower=True, guards=4) for _ in range(6)]
    play(Rules(), guarded, "spiral: realms 1-2 at 25 % tax, the others with a watchtower and 4 guards")


def main_flight():
    """@brief Flight rates in the crisis realms: does it come before the revolt,
    and does it spiral?"""
    crisis = [Plan(tax=25), Plan(tax=25)] + [Plan() for _ in range(6)]
    for adult_pct, months in ((2, 3), (3, 2), (5, 2)):
        play(Rules(flee_adult_pct=adult_pct, flee_months=months), crisis,
             f"flight {adult_pct} % a month after {months} months below 350, realms 1-2 at 25 % tax")


def main_militia():
    """@brief How many guards a realm needs, with a pool fed by two crisis realms."""
    for guards in (0, 2, 4, 6):
        plans = [Plan(tax=25), Plan(tax=25)] + [Plan(tower=True, guards=guards) for _ in range(6)]
        play(Rules(), plans, f"militia: {guards} guards in realms 3-8, realms 1-2 at 25 % tax")


if __name__ == "__main__":
    runs = {"base": main_base, "start": main_start, "spiral": main_spiral, "flight": main_flight, "militia": main_militia}
    chosen = sys.argv[1:] or ["all"]
    for name, run in runs.items():
        if "all" in chosen or name in chosen:
            run()
