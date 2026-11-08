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

    def total(self) -> int:
        return self.food + self.wood + self.stone + self.clearing


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

    def has_map(self) -> bool:
        return bool(self.terrain)

    def population(self) -> int:
        return self.children + self.adults + self.elders


def new_game(config: Config, seed: int) -> GameState:
    """@brief Build the starting state from the [start] section.
    @param config Loaded balance values.
    @param seed Seed saved in the state for future random rules.
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
    if config.map is not None:
        # Imported here: territory imports this module for Building and Zone.
        from engine.territory import start_territory
        start_territory(state, config, seed)
    return state
