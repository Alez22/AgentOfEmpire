"""@brief Game state of one city and the events produced by a turn.

Every number is an integer so that the same state + orders always give
the same result (deterministic replay). Fractions of people are kept in
accumulators measured in thousandths of a person.
"""

from dataclasses import dataclass, field

from engine.config import Config

RATIONS = ("reduced", "normal", "abundant")
UNREST_LEVELS = ("calm", "protests", "strike", "revolt")
SECTORS = ("food", "wood", "stone")


@dataclass
class Building:
    kind: str
    turns_left: int  # 0 = active, > 0 = still under construction
    # Place on the map (top-left tile, world coordinates) and a stable id
    # for orders such as demolish. Defaults: games without a map.
    id: int = 0
    x: int = -1
    y: int = -1


@dataclass
class Zone:
    """One rectangle of the town plan, corners included (world coordinates)."""
    name: str
    purpose: str  # fields, center, houses, workshops, reserve
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class Workers:
    food: int
    wood: int
    stone: int
    clearing: int = 0  # clearing claimed land (territory); 0 for games without a map
    trade: int = 0  # merchants at the market building; 0 for games without one

    def total(self) -> int:
        return self.food + self.wood + self.stone + self.clearing + self.trade


@dataclass
class ClassState:
    """@brief One class born from a building (the merchants): its own mood and
    unrest ladder, like the peasants' fields of GameState."""
    mood: int  # per mille, hidden like the peasants'
    low_mood_turns: int = 0
    unrest: str = "calm"
    # The last months at the market, oldest first: [lots filled, lots the
    # merchants could handle, 1 if others' goods were on sale]; a strike month
    # is [-1, 0, 0] and does not count (a strike vents the anger, see turn.py).
    recent_trade: list[list[int]] = field(default_factory=list)
    # Flight (village block B+C): hundredths of a person, as the births'
    # accumulator, so a small class loses someone too.
    flight_acc: int = 0


@dataclass
class Event:
    kind: str
    data: dict = field(default_factory=dict)


@dataclass
class GameState:
    turn: int
    rng_seed: int  # stored for replay; no random rule uses it yet
    food: int
    wood: int
    stone: int
    gold: int
    children: int
    adults: int
    elders: int
    birth_acc: int  # thousandths of a person, 0..999
    death_acc: list[int]  # [children, adults, elders]
    aging_acc: list[int]  # [children -> adults, adults -> elders]
    workers: Workers
    buildings: list[Building]
    free_tiles: int
    tax_rate: int
    ration: str
    mood: int  # per mille, 0..1000
    low_mood_turns: int
    unrest: str
    last_feast_turn: int  # 0 = never
    feast_gold_this_turn: int = 0  # set by hold_feast, consumed by the mood step
    # Gold a month for the counsellors, paid after the buildings' upkeep.
    # Set when the council is formed; 0 for games saved before salaries.
    council_salary: int = 0
    game_over: str | None = None  # reason, or None while the game runs
    # The territory (engine/territory.py). Empty for games without a map,
    # which count free_tiles instead. terrain and owned are rows of the
    # whole world, one character per tile: terrain ". ~ T ^" (plain,
    # river, forest, hill); owned "-" not owned, "o" owned and usable
    # (cleared land, or a standing forest), "w" owned but still wild.
    terrain: list[str] = field(default_factory=list)
    owned: list[str] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    square: list[int] = field(default_factory=list)  # [x, y] top-left tile
    next_building_id: int = 1
    # Tiles being cleared or felled, in the order they were queued:
    # [x, y, worker-months left].
    clearing_queue: list[list[int]] = field(default_factory=list)
    land_paid_total: int = 0  # gold paid for claimed tiles, into the land fund
    # Hidden land levels of the realm's site: {"food": "rich", "wood": "fair",
    # "stone": "poor"}. Empty for games without levels: buildings yield their
    # config value. Never shown to players (docs/DESIGN.md, "Land levels").
    land_levels: dict[str, str] = field(default_factory=dict)
    # The merchants' own tax, percent of the gold value of the month's trades
    # (village block A). 0 for games where the market needs no building.
    merchant_tax_rate: int = 0
    # Classes born from buildings, by name ("merchants"); empty until their
    # building is finished, and in games saved before village block A.
    classes: dict[str, ClassState] = field(default_factory=dict)
    # Village block B+C: guards the Gastaldo keeps (set_militia; 0 without a
    # watchtower), and the peasants' flight accumulators in hundredths of a
    # person, [adults, children]. 0 for games saved before.
    militia: int = 0
    flight_acc: list[int] = field(default_factory=lambda: [0, 0])

    def has_map(self) -> bool:
        return bool(self.terrain)

    def population(self) -> int:
        return self.children + self.adults + self.elders

    def guards(self) -> int:
        """@brief Guards on duty: the militia, never more than the adults."""
        return min(self.militia, self.adults)

    def free_adults(self) -> int:
        """@brief Adults the Architect may assign: the engine takes the guards first."""
        return self.adults - self.guards()


def new_game(config: Config, seed: int, site_index: int | None = None) -> GameState:
    """@brief Build the starting state from the [start] section.
    @param config Loaded balance values.
    @param seed Seed saved in the state for future random rules.
    @param site_index Which starting site of the map, for games with several
           realms (each its own site); None = the site the seed picks.
    @return Fresh state at turn 1 (January). With a [map] section the realm
            starts on the map (engine/territory.py) and its buildings come
            from the core file instead of the [start] counts.
    """
    start = config.start
    buildings = (
        [Building("farm", 0) for _ in range(start.farms)]
        + [Building("sawmill", 0) for _ in range(start.sawmills)]
        + [Building("quarry", 0) for _ in range(start.quarries)]
        + [Building("house", 0) for _ in range(start.houses)]
    )
    state = GameState(
        turn=1,
        rng_seed=seed,
        food=start.food,
        wood=start.wood,
        stone=start.stone,
        gold=start.gold,
        children=start.children,
        adults=start.adults,
        elders=start.elders,
        birth_acc=0,
        death_acc=[0, 0, 0],
        aging_acc=[0, 0],
        workers=Workers(start.workers_food, start.workers_wood, start.workers_stone),
        buildings=buildings,
        free_tiles=start.free_tiles,
        tax_rate=start.tax_rate,
        ration=start.ration,
        mood=start.mood,
        low_mood_turns=0,
        unrest="calm",
        last_feast_turn=0,
    )
    if config.market is not None and config.market.needs_building:
        state.merchant_tax_rate = config.market.merchant_tax_start
    if config.map is not None:
        # Imported here: territory imports this module for Building and Zone.
        from engine.territory import start_territory
        start_territory(state, config, seed, site_index)
    return state
