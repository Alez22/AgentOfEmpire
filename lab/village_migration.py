"""@brief Village lab, block B+C stage 2: the doors and acceptance
(docs/DESIGN.md, "The doors and acceptance"). Finds the bracketed values
before the engine gets them and checks the spirals.

Usage: docker compose run --rm -T tests python lab/village_migration.py [base|doors|seek|keep|serene|all]

Built on the real engine with stage 1 (flight, the pool, raids, the
watchtower, the militia: engine/bandits.py) and the fixed policy of
lab/village_bandits.py: 8 realms on the 8 sites, resolve_month and
resolve_world every month. On top, after the world step, this script runs
the acceptance the engine does not have yet:
- raids turned into immigration: the raiders the guards stopped stay, by
  the doors (closed none, normal keep_normal_pct, open keep_open_pct), up to
  the free beds; they leave the pool;
- acceptance: seek_pct of the pool's adults and children look for a home;
  only a realm with the mood at or above the unrest threshold, food for
  min_food_months and free beds draws them; each takes, by its doors,
  closed none, normal the smaller of free beds and empty jobs, open the
  free beds; shares in proportion to that room;
- the natives' grumbling: with food under scarce_food_months or no empty
  job, arrivals cost the peasants' mood grumble_per_pct points per 1 % of
  the population arrived (a shock, at once).
Closed doors hold only with closed_min_guards guards; else they count as normal.

Limits, on purpose:
- A fixed policy is not a council: it shows flows and edges.
- Arrivals enter as free adults; the policy puts them to work next month.
"""

import dataclasses
import sys

from engine import load_config
from engine.bandits import new_pool, resolve_world
from engine.market import RealmMonth, new_market, resolve_month
from engine import territory
from engine.turn import firewood_needed, food_needed, housing_capacity, jobs_in_sector
from lab.village_bandits import REALMS, Plan as BanditPlan, Realm as BanditRealm, _order, month_orders

MONTHS = 24
SECTORS = ("food", "wood", "stone", "trade")


@dataclasses.dataclass(frozen=True)
class Rules:
    """@brief The values of stage 2 under test (brackets of the spec)."""
    acceptance: bool = True
    seek_pct: int = 10  # of the pool, a month
    min_food_months: int = 2  # a realm draws nobody with less food than this
    keep_normal_pct: int = 25  # of the stopped raiders, normal doors
    keep_open_pct: int = 90  # open doors
    closed_min_guards: int = 2
    scarce_food_months: int = 2
    grumble_per_pct: int = 10  # mood points per 1 % of the population arrived, in scarcity
    inflow: int = 0  # lab only: wanderers from outside the world joining the pool every month


@dataclasses.dataclass
class Plan(BanditPlan):
    # Tax 5 (the free rate) for a healthy realm: with the bandits lab's gold
    # policy (5-10 %) the realms sat at mood 310-370 and fell by chance, and
    # nobody reached the unrest threshold to draw anyone (first run).
    tax: int = 5
    doors: str = "normal"
    spare_beds: int = 0  # build a house before a farm while fewer beds are free


class Realm(BanditRealm):
    def __init__(self, key, config, seed, site, plan):
        super().__init__(key, config, seed, site, plan)
        self.start_adults = self.state.adults
        self.arrived = self.arrived_children = self.from_raids = 0
        self.grumble = 0


# ---- the realm's room ---------------------------------------------------------

def free_beds(state, config):
    return max(0, housing_capacity(state, config) - state.population())


def empty_jobs(state, config):
    jobs = sum(jobs_in_sector(state, config, sector) for sector in SECTORS)
    return max(0, jobs - state.free_adults())


def doors_in_force(realm, rules):
    """@brief Closed doors need guards; without the watchtower a realm is at normal."""
    state = realm.state
    tower = any(b.kind == "watchtower" and b.turns_left == 0 for b in state.buildings)
    if not tower:
        return "normal"
    if realm.plan.doors == "closed" and state.guards() < rules.closed_min_guards:
        return "normal"
    return realm.plan.doors


def room(realm, config, rules):
    """@brief Adults this realm takes in this month (0 when it draws nobody)."""
    state = realm.state
    doors = doors_in_force(realm, rules)
    if doors == "closed" or state.mood < config.unrest.threshold:
        return 0
    if state.food < rules.min_food_months * food_needed(state, config):
        return 0
    beds = free_beds(state, config)
    return beds if doors == "open" else min(beds, empty_jobs(state, config))


# ---- acceptance -----------------------------------------------------------------

def _take(realm, adults, children, from_raid=False):
    realm.state.adults += adults
    realm.state.children += children
    realm.arrived += adults
    realm.arrived_children += children
    if from_raid:
        realm.from_raids += adults
    return adults + children


def raids_to_citizens(realm, events, config, rules, pool):
    """@brief The raiders the guards stopped stay, by the doors, up to the free beds."""
    keep_pct = {"closed": 0, "normal": rules.keep_normal_pct, "open": rules.keep_open_pct}[doors_in_force(realm, rules)]
    taken = 0
    for event in events:
        if event.kind != "raid" or not keep_pct:
            continue
        stopped = min(event.data["raiders"], event.data["guards"] * config.bandits.repel_per_guard)
        stay = min(stopped * keep_pct // 100, free_beds(realm.state, config), pool.adults)
        pool.adults -= stay
        taken += _take(realm, stay, 0, from_raid=True)
    return taken


def _shares(total, rooms):
    """@brief total split in proportion to rooms, each capped by its room (largest remainder)."""
    keys = [k for k, r in rooms.items() if r > 0]
    whole = sum(rooms[k] for k in keys)
    if not keys or not total:
        return {}
    total = min(total, whole)
    exact = {k: total * rooms[k] for k in keys}
    shares = {k: exact[k] // whole for k in keys}
    left = total - sum(shares.values())
    for k in sorted(keys, key=lambda k: -(exact[k] % whole))[:left]:
        shares[k] += 1
    return shares


def acceptance(live, config, rules, pool):
    """@brief seek_pct of the pool looks for a home among the realms that draw it."""
    seekers = pool.adults * rules.seek_pct // 100
    children = pool.children * rules.seek_pct // 100
    rooms = {r.key: room(r, config, rules) for r in live}
    shares = _shares(seekers, rooms)
    by_key = {r.key: r for r in live}
    arrived = {}
    for key, adults in shares.items():
        realm = by_key[key]
        kids = min(children * adults // seekers if seekers else 0, max(0, free_beds(realm.state, config) - adults))
        pool.adults -= adults
        pool.children -= kids
        arrived[key] = _take(realm, adults, kids)
    return arrived


def grumble(realm, config, rules, arrived):
    """@brief The natives' grumbling: only in scarcity, in proportion to the arrivals."""
    state = realm.state
    if not arrived:
        return
    scarce = state.food < rules.scarce_food_months * food_needed(state, config) or not empty_jobs(state, config)
    if not scarce:
        return
    malus = arrived * 100 // max(1, state.population()) * rules.grumble_per_pct
    state.mood = max(0, state.mood - malus)
    realm.grumble += malus


# ---- the game ---------------------------------------------------------------------

def _house_first(realm, config, orders):
    """@brief With spare_beds, a house replaces a farm while fewer beds are free
    (the bandits lab's policy builds farms first: houses fill and nobody can come)."""
    state = realm.state
    if free_beds(state, config) >= realm.plan.spare_beds:
        return orders
    if any(b.kind == "house" and b.turns_left > 0 for b in state.buildings):
        return orders
    spec = config.buildings["house"]
    if state.wood - firewood_needed(state, config) * 2 < spec.wood or state.stone < spec.stone:
        return orders
    if not territory.find_place(state, config, "house"):
        return orders
    kept = [o for o in orders if getattr(o, "action", "") != "build" or o.building != "farm"]
    return kept + [_order({"action": "build", "building": "house"})]


def orders_of(realm, config, market):
    """@brief The bandits lab's policy, plus the militia as a real engine order."""
    orders = month_orders(realm, config, market)
    if realm.plan.spare_beds:
        orders = _house_first(realm, config, orders)
    if realm.state.militia != realm.guards and any(b.kind == "watchtower" and b.turns_left == 0
                                                   for b in realm.state.buildings):
        orders.insert(0, _order({"action": "set_militia", "guards": realm.guards}))
    return orders


def play(rules, plans, label, seed=0):
    # The lab's own acceptance runs on top: the engine's [migration] (built from
    # these values, 2026-11-10) is left out so it does not run twice.
    config = dataclasses.replace(load_config(), migration=None)
    realms = [Realm(str(i + 1), config, i, i, plans[i]) for i in range(REALMS)]
    market = new_market(config, REALMS)
    pool = new_pool(config, seed, REALMS)
    pool_log = []
    for month in range(1, MONTHS + 1):
        live = [r for r in realms if not r.state.game_over]
        if not live:
            break
        months = {r.key: RealmMonth(r.state, orders_of(r, config, market)) for r in live}
        market, results = resolve_month(market, months, config)
        pool = resolve_world(pool, results, config, month)
        pool.adults += rules.inflow
        for r in live:
            r.state = results[r.key].state
            events = results[r.key].events
            r.fled_adults += sum(e.data["adults"] + e.data["merchants"] for e in events if e.kind == "flight")
            r.raids += sum(1 for e in events if e.kind == "raid")
            r.repelled += sum(1 for e in events if e.kind == "raid" and e.data["repelled"])
            r.lost_food += sum(e.data["food"] for e in events if e.kind == "raid")
        live = [r for r in realms if not r.state.game_over]
        if rules.acceptance:
            arrived = {r.key: raids_to_citizens(r, results[r.key].events, config, rules, pool) for r in live}
            for key, count in acceptance(live, config, rules, pool).items():
                arrived[key] += count
            for r in live:
                grumble(r, config, rules, arrived[r.key])
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
        print(f"  {r.name:<11} {r.plan.doors:<6} g{r.plan.guards} | adults {r.start_adults:>3} -> {s.adults:>3}"
              f" (peak {r.peak_adults:>3}) | fled {r.fled_adults:>2} | in {r.arrived:>3}+{r.arrived_children:>2}ch"
              f" (raids {r.from_raids:>2}) grumble {r.grumble:>3} | raids {r.raids:>2} rep {r.repelled:>2}"
              f" food lost {r.lost_food:>4} | food {s.food:>5} mood {s.mood:>3} (low {r.lowest_mood:>3})"
              f" {s.unrest}{end}")
    fallen = sum(1 for r in realms if r.state.game_over)
    print(f"  ALL: fallen {fallen} | fled {sum(r.fled_adults for r in realms)} | arrived"
          f" {sum(r.arrived for r in realms)}+{sum(r.arrived_children for r in realms)}ch"
          f" (from raids {sum(r.from_raids for r in realms)}) | raids {sum(r.raids for r in realms)}"
          f" | pool peak {max((a for a, _ in pool_log), default=0)}")
    print("    pool (adults+children) at months " + "  ".join(
        f"{m}: {pool_log[m - 1][0]}+{pool_log[m - 1][1]}" for m in (1, 6, 12, 18, 24) if m <= len(pool_log)))


def crisis(*others):
    """@brief Realms 1-2 in crisis (tax 25 %, the stage-1 spiral run), then the others."""
    return [Plan(tax=25), Plan(tax=25)] + [dataclasses.replace(p) for p in others]


def main_base():
    play(Rules(acceptance=False), crisis(*[Plan()] * 6), "stage 1 only: realms 1-2 in crisis, no acceptance")
    play(Rules(), crisis(*[Plan()] * 6), "acceptance, every realm at normal (no watchtower)")
    play(Rules(acceptance=False), crisis(*[Plan(spare_beds=10)] * 6), "stage 1 only, 10 spare beds")
    play(Rules(), crisis(*[Plan(spare_beds=10)] * 6), "acceptance, all normal, 10 spare beds")


def main_doors():
    guarded = dict(tower=True, guards=4, spare_beds=10)
    for doors in ("normal", "open", "closed"):
        play(Rules(), crisis(*[Plan(doors=doors, **guarded)] * 6), f"realms 3-8 watchtower, 4 guards, doors {doors}")
    mixed = [Plan(doors="open", **guarded)] * 3 + [Plan(doors="closed", **guarded)] * 3
    play(Rules(), crisis(*mixed), "realms 3-5 open, 6-8 closed (4 guards each)")


def main_seek():
    for pct in (5, 10, 20):
        play(Rules(seek_pct=pct), crisis(*[Plan(spare_beds=10)] * 6), f"seek {pct} % of the pool a month, all normal, 10 spare beds")


def main_keep():
    guarded = dict(tower=True, guards=4, spare_beds=10)
    for normal, open_ in ((25, 90), (50, 100), (10, 75)):
        play(Rules(keep_normal_pct=normal, keep_open_pct=open_),
             crisis(*[Plan(doors="normal", **guarded)] * 3, *[Plan(doors="open", **guarded)] * 3),
             f"stopped raiders kept: normal {normal} %, open {open_} % (realms 3-5 normal, 6-8 open)")


def main_inflow():
    """@brief A bigger stream of people (a stand-in for a larger world): do the
    rules hold, do the open realms grow too fast, does the grumbling bite?"""
    guarded = dict(tower=True, guards=4, spare_beds=10)
    for inflow in (4, 10):
        play(Rules(inflow=inflow), crisis(*[Plan(spare_beds=10)] * 6), f"inflow {inflow} a month, all normal")
        play(Rules(inflow=inflow), crisis(*[Plan(doors="open", **guarded)] * 3, *[Plan(doors="closed", **guarded)] * 3),
             f"inflow {inflow} a month, realms 3-5 open, 6-8 closed")
        play(Rules(inflow=inflow), crisis(*[Plan(doors="open", **guarded)] * 6), f"inflow {inflow} a month, all open")


def main_tune():
    """@brief Second round (after "inflow"): open doors took 20-47 raiders a realm,
    the grumbling (10 a 1 %) toppled 3 of 6 open realms, and the search for a
    home never found a realm with 2 months of food."""
    guarded = dict(tower=True, guards=4, spare_beds=10)
    tuned = Rules(grumble_per_pct=4, keep_open_pct=50, min_food_months=1)
    for inflow in (0, 2, 4):
        rules = dataclasses.replace(tuned, inflow=inflow)
        play(rules, crisis(*[Plan(spare_beds=10)] * 6), f"tuned, inflow {inflow}: all normal, no watchtower")
        play(rules, crisis(*[Plan(doors="open", **guarded)] * 3, *[Plan(doors="closed", **guarded)] * 3),
             f"tuned, inflow {inflow}: realms 3-5 open, 6-8 closed")
        play(rules, crisis(*[Plan(doors="open", **guarded)] * 6), f"tuned, inflow {inflow}: all open")


def main_serene():
    play(Rules(), [Plan(spare_beds=10) for _ in range(REALMS)], "a serene world: nobody in crisis, all normal, 10 spare beds")
    play(Rules(), [Plan(doors="open", tower=True, guards=2, spare_beds=10) for _ in range(REALMS)],
         "a serene world: everyone open, 2 guards, 10 spare beds")


if __name__ == "__main__":
    runs = {"base": main_base, "doors": main_doors, "seek": main_seek, "keep": main_keep, "inflow": main_inflow, "tune": main_tune,
            "serene": main_serene}
    chosen = sys.argv[1:] or ["all"]
    for name, run in runs.items():
        if "all" in chosen or name in chosen:
            run()
