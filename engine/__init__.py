"""@brief Deterministic game engine of AgentOfEmpire.

Pure Python: no database, network or LLM access. It takes a state and
the orders of a turn and returns the new state and the events.
"""

from engine.config import Config, load_config
from engine.orders import Order, parse_order
from engine.state import Event, GameState, new_game
from engine.turn import TurnResult, resolve_turn
from engine.validator import OrderResult, PlanReport, check_plans

# Stored with every game and snapshot; bump when a rule changes results.
ENGINE_VERSION = "0.1.0"

__all__ = [
    "ENGINE_VERSION",
    "Config",
    "Event",
    "GameState",
    "Order",
    "OrderResult",
    "PlanReport",
    "TurnResult",
    "check_plans",
    "load_config",
    "new_game",
    "parse_order",
    "resolve_turn",
]
