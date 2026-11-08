from dataclasses import replace

import pytest

from engine import load_config, new_game


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def start_state(config):
    return new_game(config, seed=42)


@pytest.fixture
def hex_world_config(config):
    """The hex grid with its world and core (docs/DESIGN.md, "Hex grid");
    config.toml stays square until the map page speaks hexes."""
    return replace(config, map=replace(config.map, grid="hex", world_file="world_hex.txt",
                                       core_file="core_hex.toml"))
