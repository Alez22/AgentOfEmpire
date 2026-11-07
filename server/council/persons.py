"""@brief The persons who sit on a council: drawn from personas.toml.

A role is the office and stays generic; the person brings name, gender,
character, story, model and salary. Gender lives here, not in the role
(the Architect may be a man or a woman).

Games created before personas have no person data: they keep the names
and genders they always had (DEFAULT_GENDERS), so nothing changes.
"""

import random
import tomllib
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("personas.toml")
COUNCIL_ROLES = ("treasurer", "architect", "chancellor")
DEFAULT_GENDERS = {"treasurer": "m", "architect": "f", "chancellor": "m"}
# Italian title with its article, by role and gender.
TITLES = {
    ("treasurer", "m"): "il Tesoriere", ("treasurer", "f"): "la Tesoriera",
    ("architect", "m"): "l'Architetto", ("architect", "f"): "l'Architetta",
    ("chancellor", "m"): "il Cancelliere", ("chancellor", "f"): "la Cancelliera",
    ("square_voice", "f"): "la Voce della piazza", ("people", "m"): "il popolo",
}
GENDER_WORDS = {"m": "a man", "f": "a woman"}


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    with open(path, "rb") as catalog_file:
        return tomllib.load(catalog_file)["persona"]


def draw_council(catalog: list[dict], seed: int, realm_index: int, taken: set[str]) -> dict[str, dict]:
    """@brief One moderate person per council role, by the game's seed.
    @param taken ids already sitting in another realm of this game (updated).
    @return role -> persona.
    @throws ValueError if the catalog has too few moderates for this game.
    """
    rng = random.Random(f"{seed}:council:{realm_index}")  # own generator: the engine's is untouched
    council = {}
    for role in COUNCIL_ROLES:
        free = [p for p in catalog if p["role"] == role and p["group"] == "moderate" and p["id"] not in taken]
        if not free:
            raise ValueError(f"no free moderate {role} left in the catalog")
        person = rng.choice(free)
        taken.add(person["id"])
        council[role] = person
    return council


def gender_of(role: str, person: dict) -> str:
    return person.get("gender") or DEFAULT_GENDERS.get(role, "m")


def title(role: str, person: dict) -> str:
    """@brief "l'Architetta", "il Tesoriere"... from the person's gender."""
    gender = gender_of(role, person)
    return TITLES.get((role, gender)) or TITLES.get((role, "m")) or TITLES.get((role, "f")) or role


def display_name(role: str, person: dict) -> str:
    """@brief "Gisella da Valle, l'Architetta"; without a person (older games)
    the capitalised title alone, as it always was ("L'Architetta")."""
    office = title(role, person)
    if person.get("name"):
        return f"{person['name']}, {office}"
    return office[0].upper() + office[1:]


def person_lines(role: str, person: dict) -> str:
    """@brief Who this person is, for its own prompts ("" for older games)."""
    if not person.get("name"):
        return ""
    lines = [f"You are {person['name']} ({GENDER_WORDS[gender_of(role, person)]})."]
    if person.get("resume"):
        lines.append(f"Your story: {person['resume']}")
    return "\n" + "\n".join(lines) + "\n"
