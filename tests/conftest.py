import pytest

from engine import load_config, new_game


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def start_state(config):
    return new_game(config, seed=42)
