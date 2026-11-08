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
    """The hex grid with its world and core (docs/DESIGN.md, "Hex grid"),
    named on its own: the same as config.toml since 2026-11-08."""
    return replace(config, map=replace(config.map, grid="hex", world_file="world_hex.txt",
                                       core_file="core_hex.toml"))


@pytest.fixture
def square_config():
    """The square grid of the games saved before the hex grid: their rules
    must stay as they were, so their replays stay exact. Built from the file,
    not from the config fixture, which square-grid modules override with it."""
    config = load_config()
    return replace(config, map=replace(config.map, grid="square", world_file="world.txt",
                                       core_file="core.toml"))
