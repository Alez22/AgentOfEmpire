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
    building: Literal["farm", "sawmill", "quarry", "house"]
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


class SetTaxOrder(BaseOrder):
    action: Literal["set_tax"]
    rate: int = Field(ge=0)


class SetRationOrder(BaseOrder):
    action: Literal["set_ration"]
    ration: Literal["reduced", "normal", "abundant"]


class HoldFeastOrder(BaseOrder):
    action: Literal["hold_feast"]
    gold: int = Field(gt=0)


class ZoneSpec(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    purpose: Literal["fields", "center", "houses", "workshops", "reserve"]
    x1: int
    y1: int
    x2: int
    y2: int


class SetZonesOrder(BaseOrder):
    """The whole town plan; it replaces the one in force."""
    action: Literal["set_zones"]
    zones: list[ZoneSpec]


class DemolishOrder(BaseOrder):
    action: Literal["demolish"]
    building_id: int = Field(ge=1)


Order = Annotated[
    BuildOrder | AssignWorkersOrder | SetTaxOrder | SetRationOrder | HoldFeastOrder
    | SetZonesOrder | DemolishOrder,
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
