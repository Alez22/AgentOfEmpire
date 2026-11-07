"""@brief Prototype personality: fixed role + five traits (0..1000).

Traits are drawn near the centre at game start (moderate ministers) and
reach the prompt as words, never as numbers.
"""

import random

TRAITS = ("prudence", "loyalty", "ambition", "honesty", "competence")
START_MIN, START_MAX = 350, 650  # "near the centre" from the design doc
LOW_BELOW, HIGH_ABOVE = 420, 580

# trait -> (low, middle, high) wording used in the prompt
TRAIT_WORDS = {
    "prudence": ("bold, willing to take risks", "balanced between caution and boldness", "cautious"),
    "loyalty": ("of uncertain loyalty", "reasonably loyal", "very loyal"),
    "ambition": ("unambitious", "moderately ambitious", "ambitious"),
    "honesty": ("inclined to bend the truth", "mostly honest", "scrupulously honest"),
    "competence": ("of modest competence", "competent", "highly competent"),
}


def generate_traits(seed: int, realm_id: int, role: str) -> dict[str, int]:
    """@brief Same game seed + realm + role always gives the same traits.
    Uses its own Random instance: the engine's determinism is untouched.
    """
    rng = random.Random(f"{seed}:{realm_id}:{role}")
    return {trait: rng.randint(START_MIN, START_MAX) for trait in TRAITS}


def describe_traits(traits: dict[str, int]) -> str:
    """@brief Plain words for the prompt; a missing trait counts as average."""
    words = []
    for trait in TRAITS:
        value = traits.get(trait, 500)
        low, middle, high = TRAIT_WORDS[trait]
        if value < LOW_BELOW:
            words.append(low)
        elif value > HIGH_ABOVE:
            words.append(high)
        else:
            words.append(middle)
    return ", ".join(words)
