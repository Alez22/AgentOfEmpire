"""@brief Roads of the world, phase 2: how often a caravan to the fair meets
a band (docs/DESIGN.md, "Roads of the world", option A decided with the
owner 2026-11-13: an ambush zone, not the same hex).

Usage: docker compose run --rm -T tests python lab/caravans_map.py

The question: a caravan jumps several hexes a week and a band jumps up to 8
road units, so "same hex, same week" almost never happens. Option A: each
week the caravan marks every hex it crossed; if one of them lies within
`radius` hexes of a band (where the band stands at the end of the week),
the caravan is met. Radii under test: 2, 4, 6.

Observer only: the real engine plays the worlds of lab/bands_map.py (8
realms, realms 1-2 in crisis, the engine's [bands]), and this script
records the bands' place each week through a hook on the engine's weekly
sightings. Caravans do not change the economy and bands do not hunt them:
the numbers say how exposed the roads are, not what a robbery costs.

The caravans (lab simplifications, to decide in the spec):
- the fair: the free hex nearest the middle of the map;
- every month every playing realm sends one caravan out (doorstep -> fair)
  and one back (fair -> doorstep), both leaving in week 1 (an upper bound:
  in a game a realm trades in some months only);
- the road: the engine's cheapest road (RoadMap.roads, realms' land
  closed), walked at `speed` road units a week, as the bands walk;
- a leg met once stops (it would turn back); bands under merge_under
  adults count too (they are still armed men by the road), shown apart.

The fair's peace (run 2, asked by the owner 2026-11-13): in the first run
the start bands camped in the free middle of the map, by the fair, where
every road ends. With FAIR_GAPS > 0 no band camps within that many hexes of
the fair: the hexes near it count as a realm's land for the engine's camp
choices (start camps, new camps of fugitives, splits), through a hook on
RoadMap's steps to the land. A fallen realm's band still camps on its land.

Printed per fair gap, seed and speed: the road units from each realm to the fair
(weeks a leg takes), then per radius the share of legs met, per realm and
in all, and the week of the meeting.
"""

import engine.bands as engine_bands
from engine import load_config
from engine.territory import hex_distance
from lab.bands_map import MONTHS, SEEDS, play
from lab.bands_map import Values
from lab.village_fallen import WORLDS

RADII = (2, 4, 6)
SPEEDS = (8,)  # road units a week, as the bands (6 changed little in the first run)
FAIR_GAPS = (0, 6, 10)  # hexes around the fair where no band camps; 0: the engine as it is


class Recorder:
    """@brief Hook on the engine's weekly sightings: walks the caravans of the
    week and checks them against the bands where they stand now."""

    def __init__(self, speed: int):
        self.speed = speed
        self.legs = []  # this month's legs: dicts with realm, path, index, met
        self.met = {radius: {} for radius in RADII}  # radius -> {realm: legs met}
        self.small = {radius: 0 for radius in RADII}  # met only by bands under merge_under
        self.week_met = {radius: [0, 0, 0, 0] for radius in RADII}
        self.sent = {}  # realm -> legs sent
        self.units = {}  # realm -> road units to the fair (first month)

    def __call__(self, pool, states, events, roads, rules, week, seen):
        ORIGINAL_SIGHTINGS(pool, states, events, roads, rules, week, seen)
        if week == 1:
            self._send(states, roads)
        for leg in self.legs:
            if leg["index"] == len(leg["path"]) - 1 and week > 1:
                continue  # arrived in an earlier week: off the road
            crossed = self._walk(leg, roads)
            self._check(leg, crossed, pool, rules, week)

    def _send(self, states, roads):
        """@brief Week 1: one leg out and one back for every playing realm."""
        fair = _fair(roads)
        self.legs = []
        for key in states:
            cost, reached = roads.roads(fair, roads.doorstep(key))
            if reached is None:
                continue
            path = _path(roads, cost, fair, reached)
            self.units.setdefault(key, cost[reached])
            self.sent[key] = self.sent.get(key, 0) + 2
            self.legs.append({"realm": key, "path": path, "index": 0, "met": set()})
            self.legs.append({"realm": key, "path": path[::-1], "index": 0, "met": set()})

    def _walk(self, leg, roads):
        """@brief One week along the leg's path, up to speed units.
        @return The hexes crossed this week, the start one included."""
        path, index = leg["path"], leg["index"]
        crossed, spent = [path[index]], 0
        while index + 1 < len(path):
            tile = path[index + 1]
            spent += roads.cost[roads.terrain[tile[1]][tile[0]]]
            if spent > self.speed:
                break
            index += 1
            crossed.append(tile)
        leg["index"] = index
        return crossed

    def _check(self, leg, crossed, pool, rules, week):
        """@brief Per radius, the first meeting of the leg (a met leg stays met)."""
        for radius in RADII:
            if radius in leg["met"]:
                continue
            near = [b for b in pool.bands if b.adults > 0
                    and min(hex_distance(b.x, b.y, x, y) for x, y in crossed) <= radius]
            if not near:
                continue
            leg["met"].add(radius)
            self.met[radius][leg["realm"]] = self.met[radius].get(leg["realm"], 0) + 1
            self.week_met[radius][week - 1] += 1
            if all(b.adults < rules.merge_under for b in near):
                self.small[radius] += 1


def _fair(roads):
    """@brief The free hex nearest the middle of the map (ties by (y, x))."""
    middle = roads.size // 2
    free = [(x, y) for y in range(roads.size) for x in range(roads.size) if (x, y) not in roads.owner]
    return min(free, key=lambda t: (hex_distance(*t, middle, middle), t[1], t[0]))


def _path(roads, cost, start, goal):
    """@brief The cheapest road from start to goal, back along decreasing cost."""
    path = [goal]
    while path[-1] != start:
        path.append(min((t for t in engine_bands.neighbours(roads.config, *path[-1]) if t in cost),
                        key=lambda t: cost[t]))
    return path[::-1]


ORIGINAL_SIGHTINGS = engine_bands._sightings
ORIGINAL_STEPS_TO_LAND = engine_bands.RoadMap._steps_to_land


def fair_peace(gap: int):
    """@brief A RoadMap._steps_to_land that also puts the hexes within gap of
    the fair at 0 steps, so no camp choice takes them (any camp gap >= 0)."""
    def steps_to_land(roads):
        steps = ORIGINAL_STEPS_TO_LAND(roads)  # owner is set before this runs in RoadMap.__init__
        fair = _fair(roads)
        for tile in list(steps):
            if hex_distance(*tile, *fair) <= gap:
                steps[tile] = 0
        return steps
    return steps_to_land


def report(recorder):
    keys = sorted(recorder.sent)
    weeks = " ".join(f"{k}:{recorder.units[k]}u/{-(-recorder.units[k] // recorder.speed)}w" for k in keys)
    lines = [f"    to the fair: {weeks}"]
    sent = sum(recorder.sent.values()) or 1
    for radius in RADII:
        met = recorder.met[radius]
        per = " ".join(f"{k}:{met.get(k, 0) * 100 // recorder.sent[k]:>3}%" for k in keys)
        total = sum(met.values())
        lines.append(f"    radius {radius}: met {total:>3}/{sent} = {total * 100 // sent:>3} % | {per}"
                     f" | small bands only {recorder.small[radius]:>3} | by week {recorder.week_met[radius]}")
    return "\n".join(lines)


def run(config, plans, speed, seed, gap):
    """@brief One game with the hooks in place, always taken off after."""
    recorder = Recorder(speed)
    engine_bands._sightings = recorder
    if gap:
        engine_bands.RoadMap._steps_to_land = fair_peace(gap)
    try:
        _, stats = play(config, plans, "engine", seed, Values())
    finally:
        engine_bands._sightings = ORIGINAL_SIGHTINGS
        engine_bands.RoadMap._steps_to_land = ORIGINAL_STEPS_TO_LAND
    raids = sum(stats["raids"].values())
    print(f"  fair gap {gap:>2} speed {speed} seed {seed} | raids {raids:>3} | bands peak {stats['bands_peak']:>2}"
          f" adults peak {stats['adults_peak']:>3}")
    print(report(recorder))


def main():
    config = load_config()  # the engine's [bands]
    for world, plans in WORLDS.items():
        print(f"\n== {world} (realms 1-2 in crisis), {MONTHS} months")
        for gap in FAIR_GAPS:
            for speed in SPEEDS:
                for seed in SEEDS:
                    run(config, plans, speed, seed, gap)


if __name__ == "__main__":
    main()
