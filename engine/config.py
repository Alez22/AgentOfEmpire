"""@brief Load the balance values from config.toml into frozen dataclasses.

Dataclass constructors reject missing or unknown keys, so a typo in the
TOML file fails loudly at load time instead of silently using a default.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")


@dataclass(frozen=True)
class StartConfig:
    children: int
    adults: int
    elders: int
    food: int
    wood: int
    stone: int
    gold: int
    free_tiles: int
    workers_food: int
    workers_wood: int
    workers_stone: int
    tax_rate: int
    ration: str
    mood: int
    farms: int
    sawmills: int
    quarries: int
    houses: int


@dataclass(frozen=True)
class BuildingConfig:
    wood: int
    stone: int
    gold: int
    build_turns: int
    jobs: int
    output_per_worker: int
    sector: str
    housing: int
    # Footprint and terrain on the map. Defaults: games saved before the
    # territory had no map, so the values are never read for them.
    width: int = 1
    height: int = 1
    terrain: str = "plain"
    needs_forest: bool = False


@dataclass(frozen=True)
class EconomyConfig:
    food_per_child: int
    food_per_adult: int
    food_per_elder: int
    ration_reduced_pct: int
    ration_normal_pct: int
    ration_abundant_pct: int
    farm_winter_pct: int
    farm_spring_pct: int
    farm_summer_pct: int
    farm_autumn_pct: int
    tax_divisor: int
    max_tax_rate: int
    upkeep_gold_per_building: int
    unpaid_upkeep_output_pct: int
    food_spoilage_pct: int
    reserve_alert_months: int


@dataclass(frozen=True)
class DemographyConfig:
    birth_permille_per_adult: int
    low_mood_births_below: int
    low_mood_births_pct: int
    high_mood_births_above: int
    high_mood_births_pct: int
    death_child_permille: int
    death_adult_permille: int
    death_elder_permille: int
    famine_death_permille_per_missing_pct: int
    child_to_adult_permille: int
    adult_to_elder_permille: int


@dataclass(frozen=True)
class MoodConfig:
    base: int
    approach_pct: int
    ration_reduced: int
    ration_abundant: int
    tax_free_rate: int
    tax_per_point: int
    famine_per_missing_pct: int
    famine_max: int
    reserve_bonus_months: int
    reserve_bonus: int
    housing_full: int
    per_death: int
    feast_gold_per_point: int
    feast_max: int
    feast_repeat_pct: int
    # Immediate mood loss in the month of a famine (a feast in reverse).
    # Defaults 0: games saved before these keys existed keep their own rules,
    # so their results and replays do not change.
    famine_shock_per_missing_pct: int = 0
    death_shock: int = 0


@dataclass(frozen=True)
class UnrestConfig:
    threshold: int
    protest_turns: int
    strike_turns: int
    revolt_turns: int
    strike_output_pct: int


@dataclass(frozen=True)
class PeopleConfig:
    """Limits of what the people may decide each month (engine/people.py)."""
    content_above: int  # mood above this: content band
    discontent_below: int  # mood below this: discontented band
    effort_content: list[int]  # [min, max] percent added to all yields
    effort_neutral: list[int]
    effort_discontent: list[int]
    birth_content: list[int]  # [min, max] percent multiplier of births
    birth_neutral: list[int]
    birth_discontent: list[int]
    # Proportional petitions (2026-11-07): granting is worth half the relief
    # the asked order brings to the people's burdens, within [min, max];
    # refusing (or not answering) costs the same. Computed when the people
    # decide and stored with the decision (petition_weight).
    petition_min_mood: int | None = None
    petition_max_mood: int | None = None
    # Fixed values of the first version, kept for games saved with them.
    petition_granted_mood: int | None = None
    petition_refused_mood: int | None = None


@dataclass(frozen=True)
class MapConfig:
    """The territory: map files, starting sites, demolition (engine/territory.py)."""
    world_file: str  # in engine/maps/
    core_file: str
    sites: list[list[int]]  # [x, y] top-left tile of each starting core
    core_size: int
    square_size: int
    max_zones: int
    demolish_gold: int
    demolish_refund_pct: int  # of the building's wood and stone
    claim_base_gold: int
    claim_step_tiles: int
    claim_max_per_order: int
    clear_work_plain: int  # worker-months to clear one tile
    clear_work_hill: int
    clear_work_forest: int
    fell_wood_per_work: int  # wood for each worker-month spent felling
    # Land levels of each site, same order as sites: [food, wood, stone],
    # each "poor", "fair" or "rich" (docs/DESIGN.md, "Market, needs and land
    # levels"). None for games saved before: every realm yields the same.
    site_levels: list[list[str]] | None = None


@dataclass(frozen=True)
class NeedsConfig:
    """Steady needs for wood and stone (lab/market_closed.py, 2026-11-08)."""
    firewood_months: list[int]  # month numbers, 1 = January
    firewood_people: int  # 1 wood per this many people, each firewood month
    cold_shock_per_pct: int  # mood lost at once per missing percent of firewood
    stone_upkeep_buildings: int  # 1 stone per this many active buildings, each month
    worn_output_loss_pct: int  # share of the missing stone percent lost from the month's output


@dataclass(frozen=True)
class MarketConfig:
    """The common market of a game (engine/market.py)."""
    lot_units: int  # units per lot; prices are gold per lot
    start_price: dict[str, int]  # per good; the bounds are relative to it
    margin_pct: int  # buyers pay price + margin, sellers get price - margin
    step_pct: int  # monthly price move
    min_price_pct: int
    max_price_pct: int
    cover_months: int  # the price falls when goods on sale exceed this many months of asked lots
    start_stock_per_realm: dict[str, int]  # units, nobody's goods; never counted as too much


@dataclass(frozen=True)
class LevelsConfig:
    """Output per worker by land level: {"poor": 14, "fair": 15, "rich": 16}."""
    food: dict[str, int]
    wood: dict[str, int]
    stone: dict[str, int]


@dataclass(frozen=True)
class Config:
    start: StartConfig
    buildings: dict[str, BuildingConfig]
    economy: EconomyConfig
    demography: DemographyConfig
    mood: MoodConfig
    unrest: UnrestConfig
    # None for games saved before the people decided anything: they keep
    # their own rules and replay unchanged.
    people: PeopleConfig | None = None
    # None for games saved before the territory: no map, free_tiles instead.
    map: MapConfig | None = None
    # None for games saved before the market's needs and land levels.
    needs: NeedsConfig | None = None
    levels: LevelsConfig | None = None
    market: MarketConfig | None = None  # None: no market, trade orders are refused


def load_raw_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """@brief Read the TOML balance file as plain data (stored with each game).
    @param path Location of the TOML file (defaults to engine/config.toml).
    """
    with open(path, "rb") as config_file:
        return tomllib.load(config_file)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """@brief Read and type-check the TOML balance file.
    @param path Location of the TOML file (defaults to engine/config.toml).
    @return Immutable Config.
    @throws TypeError if a key is missing or unknown.
    """
    return config_from_dict(load_raw_config(path))


def config_from_dict(raw: dict) -> Config:
    """@brief Type-check plain config data (from the TOML file or a saved game).
    @throws TypeError if a key is missing or unknown.
    """
    buildings = {
        kind: BuildingConfig(**values) for kind, values in raw["buildings"].items()
    }
    return Config(
        start=StartConfig(**raw["start"]),
        buildings=buildings,
        economy=EconomyConfig(**raw["economy"]),
        demography=DemographyConfig(**raw["demography"]),
        mood=MoodConfig(**raw["mood"]),
        unrest=UnrestConfig(**raw["unrest"]),
        people=PeopleConfig(**raw["people"]) if "people" in raw else None,
        map=MapConfig(**raw["map"]) if "map" in raw else None,
        needs=NeedsConfig(**raw["needs"]) if "needs" in raw else None,
        levels=LevelsConfig(**raw["levels"]) if "levels" in raw else None,
        market=MarketConfig(**raw["market"]) if "market" in raw else None,
    )
