"""@brief Council settings from server/council.toml (+ environment overrides)."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[1] / "council.toml"


@dataclass(frozen=True)
class ModelPrice:
    input: float  # USD per million input tokens
    output: float  # USD per million output tokens


@dataclass(frozen=True)
class CouncilSettings:
    provider: str  # "fake" or "openrouter"
    base_url: str
    language: str
    budget_usd_per_game: float
    timeout_seconds: int  # deadline on the whole call
    max_output_tokens: int  # reasoning included
    max_directives_per_turn: int
    history_turns: int
    max_lessons: int
    max_audience_messages_per_turn: int
    models: dict[str, str]  # role -> model id (roles without a person: Voice, people)
    model_tiers: dict[str, str]  # a person's tier (low, medium, high) -> model id
    reasoning_effort: dict[str, str]  # role -> effort; missing role = model default
    prices: dict[str, ModelPrice]  # model id -> price
    # Models whose providers reject a parameter (with require_parameters on,
    # sending it would leave no provider): the client leaves it out.
    models_without_json_schema: tuple[str, ...] = ()
    models_without_reasoning: tuple[str, ...] = ()


def load_settings(path: Path = DEFAULT_SETTINGS_PATH) -> CouncilSettings:
    """@brief Read council.toml. COUNCIL_PROVIDER in the environment overrides
    the provider, so switching to real models needs no file edit.
    @throws TypeError on missing or unknown keys.
    """
    with open(path, "rb") as settings_file:
        raw = tomllib.load(settings_file)
    # An empty variable (compose passes "" when it is not set) keeps the file value.
    raw["provider"] = os.environ.get("COUNCIL_PROVIDER") or raw["provider"]
    if raw["provider"] not in ("fake", "openrouter"):
        raise ValueError(f"unknown council provider '{raw['provider']}'")
    raw["prices"] = {model: ModelPrice(**price) for model, price in raw.get("prices", {}).items()}
    raw.setdefault("reasoning_effort", {})
    raw["models_without_json_schema"] = tuple(raw.get("models_without_json_schema", ()))
    raw["models_without_reasoning"] = tuple(raw.get("models_without_reasoning", ()))
    return CouncilSettings(**raw)
