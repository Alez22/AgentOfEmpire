"""@brief Catalog of the orders a sovereign or a minister can issue.

These Pydantic models are the single source of truth for the action
catalog: FastAPI publishes them as OpenAPI (-> TypeScript types) and the
same JSON schema is given to the LLMs as their mandatory reply format.
Only shape checks live here; checks that need the game state or the
config (costs, max tax rate, free tiles, the map) are in validator.py.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class BaseOrder(BaseModel):
    # Lower priority runs first; Python's sort is stable, so equal
    # priorities keep their submission order.
    priority: int = 0


class BuildOrder(BaseOrder):
    action: Literal["build"]
    building: Literal["farm", "sawmill", "quarry", "house", "market", "watchtower"]
    # On the map: the zone to build in and, optionally, the top-left tile.
    # Without them the engine picks the place nearest the square.
    zone: str | None = None
    x: int | None = None
    y: int | None = None


class AssignWorkersOrder(BaseOrder):
    action: Literal["assign_workers"]
    food: int = Field(ge=0)
    wood: int = Field(ge=0)
    stone: int = Field(ge=0)
    clearing: int = Field(default=0, ge=0)  # totals like the others: missing = 0
    trade: int = Field(default=0, ge=0)  # merchants at the market building


class SetTaxOrder(BaseOrder):
    action: Literal["set_tax"]
    rate: int = Field(ge=0)


class SetRationOrder(BaseOrder):
    action: Literal["set_ration"]
    ration: Literal["reduced", "normal", "abundant"]


class SetMerchantTaxOrder(BaseOrder):
    """The merchants' own tax, percent of the gold value of the month's trades."""
    action: Literal["set_merchant_tax"]
    rate: int = Field(ge=0)


class SetMilitiaOrder(BaseOrder):
    """The Gastaldo's guards (village block B+C): adults kept on guard, taken
    before the Architect's workers. Only with a finished watchtower."""
    action: Literal["set_militia"]
    guards: int = Field(ge=0)


class HoldFeastOrder(BaseOrder):
    action: Literal["hold_feast"]
    gold: int = Field(gt=0)


class ZoneSpec(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    purpose: Literal["fields", "center", "houses", "workshops", "reserve", "market", "watch"]
    x1: int
    y1: int
    x2: int
    y2: int


class SetZonesOrder(BaseOrder):
    """The whole town plan; it replaces the one in force."""
    action: Literal["set_zones"]
    zones: list[ZoneSpec]


class ClaimTilesOrder(BaseOrder):
    """Bordering tiles inside a zone of the town plan, or of one terrain on one
    side of the square. Exactly one of zone and direction (checked in the
    validator); terrain is required with a direction, optional with a zone."""
    action: Literal["claim_tiles"]
    count: int = Field(ge=1)
    zone: str | None = None
    direction: Literal["north", "south", "east", "west"] | None = None
    terrain: Literal["plain", "forest", "hill"] | None = None


class FellForestOrder(BaseOrder):
    """Queue owned forest tiles for felling (wood now, plain afterwards)."""
    action: Literal["fell_forest"]
    count: int = Field(ge=1)
    direction: Literal["north", "south", "east", "west"] | None = None


class DemolishOrder(BaseOrder):
    action: Literal["demolish"]
    building_id: int = Field(ge=1)


class TradeOrder(BaseOrder):
    """Buy or sell lots at the common market (engine/market.py). Filled at the
    start of the month, before the realm's other orders."""
    action: Literal["trade"]
    good: Literal["food", "wood", "stone"]
    side: Literal["buy", "sell"]
    lots: int = Field(ge=1)


Order = Annotated[
    BuildOrder | AssignWorkersOrder | SetTaxOrder | SetRationOrder | HoldFeastOrder
    | SetZonesOrder | DemolishOrder | ClaimTilesOrder | FellForestOrder | TradeOrder
    | SetMerchantTaxOrder | SetMilitiaOrder,
    Field(discriminator="action"),
]

_order_adapter = TypeAdapter(Order)


def parse_order(raw_order: dict) -> tuple[Order | None, str | None, str]:
    """@brief Turn untrusted JSON (from the browser or an LLM) into an order.
    @param raw_order Decoded JSON object.
    @return (order, None, "") on success, or (None, code, message) where
            code is UNKNOWN_ACTION or INVALID_PARAM.
    """
    try:
        return _order_adapter.validate_python(raw_order), None, ""
    except ValidationError as error:
        first_error = error.errors()[0]
        # A missing or unknown "action" tag means the action is not in the catalog.
        if first_error["type"] in ("union_tag_invalid", "union_tag_not_found"):
            return None, "UNKNOWN_ACTION", first_error["msg"]
        return None, "INVALID_PARAM", first_error["msg"]
