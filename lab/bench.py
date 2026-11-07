"""@brief Bench of the council models: the same stored briefings to every candidate.

Usage (inside the server container, which has the database and the key):
  docker compose exec -T server python lab/bench.py OUT_FILE [--repeat N] [--only ID,ID] MODEL[:EFFORT] ...
  e.g. ... lab/bench.py /tmp/bench.txt z-ai/glm-5.3-flash:low openai/gpt-oss-120b:low

Each scenario of lab/bench_scenarios.toml is a stored call (model_calls)
with a known trap. Its system prompt and briefing are sent again; for the
ministers the memory section is rebuilt with the current memory code, and
the craft block and the manual phrase of the system prompt with the current
files, so a fix to either is measured, not the old wording.

Nothing is written to the database: no game, no order, no model_calls row.
Hidden costs: real OpenRouter calls, one at a time, each blocking up to
timeout_seconds (council.toml). 8 scenarios x 3 repeats x 4 models = 96
calls, about $0.05-0.10.

Limit: the briefings are snapshots. If prompts or the manual change, the
system prompts and the rest of each briefing stay as they were stored.
"""

import os
import sys
import tomllib
from pathlib import Path

import psycopg

from server.council import memory, persons
from server.council.llm import LLMError, OpenRouterClient
from server.council.meeting import (PROMPTS_DIR, _ChancellorReply, _ChancellorSchema, _MinisterReply, _MinisterSchema,
                                    _refusal_reason, _validate_plan, _validate_proposals)
from server.council.settings import load_settings

SCENARIOS_PATH = Path(__file__).with_name("bench_scenarios.toml")
HISTORY_HEADER = "## Your recent proposals and what followed"


def load_call(conn, call_id: int) -> dict:
    row = conn.execute(
        "SELECT c.prompt_system, c.prompt_user, c.turn, a.id, a.role, a.realm_id, r.game_id"
        " FROM model_calls c JOIN actors a ON a.id = c.actor_id JOIN realms r ON r.id = a.realm_id"
        " WHERE c.id = %s", (call_id,),
    ).fetchone()
    keys = ("system", "user", "turn", "actor_id", "role", "realm_id", "game_id")
    return dict(zip(keys, row))


def _names_by_actor(conn, realm_id: int) -> dict[int, str]:
    rows = conn.execute("SELECT id, role, personality FROM actors WHERE realm_id = %s", (realm_id,))
    return {actor_id: persons.display_name(role, personality) for actor_id, role, personality in rows}


def rebuild_memory(conn, call: dict, history_turns: int) -> str:
    """@brief The stored briefing with the minister's memory section written
    by the current code (unchanged for the Chancellor or with no memory)."""
    user = call["user"]
    if call["role"] == "chancellor" or HISTORY_HEADER not in user:
        return user
    entries = memory.consequence_lines(
        conn, call["game_id"], call["realm_id"], call["actor_id"], call["role"],
        call["turn"] - history_turns, call["turn"], _names_by_actor(conn, call["realm_id"]),
    )
    new_section = "\n".join([HISTORY_HEADER] + [f"- {entry}" for entry in entries])
    before, rest = user.split(HISTORY_HEADER, 1)
    # The section ends where the next "## " section starts.
    cut = rest.find("\n## ")
    after = rest[cut:] if cut >= 0 else ""
    return before + new_section + after


OLD_MANUAL_PHRASE = ": a half-filled building already pays."


def rebuild_system(role: str, system: str) -> str:
    """@brief The stored system prompt with the current craft and manual
    wording, so a change to either is measured. The craft block runs from
    its first line to the next blank line."""
    system = system.replace(OLD_MANUAL_PHRASE, ".")
    path = PROMPTS_DIR / f"expertise_{role}.txt"
    if not path.exists():
        return system
    craft = path.read_text().strip()
    first_line = craft.splitlines()[0]
    start = system.find(first_line)
    if start < 0:
        return system
    end = system.find("\n\n", start)
    return system[:start] + craft + (system[end:] if end >= 0 else "")


def _matches(order: dict, pattern: dict) -> bool:
    for key, value in pattern.items():
        if key == "food_below":
            if order.get("action") != "assign_workers" or order.get("food", value) >= value:
                return False
        elif order.get(key) != value:
            return False
    return True


def _empties_a_sector(order: dict) -> bool:
    return order.get("action") == "assign_workers" and (order.get("wood") == 0 or order.get("stone") == 0)


def judge(role: str, text: str) -> dict:
    """@brief Parse the reply as the meeting would; return the valid orders and the words."""
    reply_model = _ChancellorReply if role == "chancellor" else _MinisterReply
    parsed, error = _refusal_reason(text, reply_model, None)
    if parsed is None:
        return {"valid": False, "error": error, "orders": [], "words": text[:600]}
    if role == "chancellor":
        plan, _ = _validate_plan(parsed.plan)
        orders = [item["order"] for item in plan]
        words = parsed.summary
    else:
        orders, _ = _validate_proposals(role, parsed.proposals)
        words = parsed.report
    return {"valid": True, "error": "", "orders": orders, "words": words}


def score(scenario: dict, verdict: dict) -> dict:
    orders = verdict["orders"]
    return {
        "forbidden": [o for o in orders if any(_matches(o, p) for p in scenario.get("forbidden", []))],
        "missing": [p for p in scenario.get("expected", []) if not any(_matches(o, p) for o in orders)],
        "empty_sector": any(_empties_a_sector(o) for o in orders),
    }


def _schema(role: str) -> dict:
    return (_ChancellorSchema if role == "chancellor" else _MinisterSchema).model_json_schema()


def run_one(client, candidate: str, role: str, system: str, user: str) -> dict:
    model, _, effort = candidate.partition(":")
    try:
        reply = client.complete(role, model, system, user, _schema(role), effort or None)
    except LLMError as error:
        return {"status": error.status, "error": str(error)[:200], "valid": False, "orders": [],
                "words": "", "tokens": 0, "cost": 0.0, "seconds": 0.0}
    verdict = judge(role, reply.text)
    return {"status": "ok", **verdict, "tokens": reply.output_tokens, "cost": reply.cost_usd,
            "seconds": reply.latency_ms / 1000}


def _order_list(orders: list[dict]) -> str:
    return "; ".join(memory.order_text(o) for o in orders) or "nothing"


def main(argv: list[str]) -> None:
    out_path, args = Path(argv[0]), argv[1:]
    repeat, only = 3, None
    if args[:1] == ["--repeat"]:
        repeat, args = int(args[1]), args[2:]
    if args[:1] == ["--only"]:  # comma-separated scenario ids, e.g. 7-chancellor-abundant
        only, args = set(args[1].split(",")), args[2:]
    candidates = args
    settings = load_settings()
    client = OpenRouterClient(settings.base_url, os.environ.get("OPENROUTER_API_KEY", ""),
                              settings.timeout_seconds, settings.prices, settings.max_output_tokens,
                              settings.models_without_json_schema, settings.models_without_reasoning)
    with open(SCENARIOS_PATH, "rb") as scenarios_file:
        scenarios = [s for s in tomllib.load(scenarios_file)["scenario"] if only is None or s["id"] in only]

    totals = {c: {"runs": 0, "valid": 0, "forbidden": 0, "missing": 0, "empty": 0,
                  "tokens": 0, "cost": 0.0, "seconds": 0.0} for c in candidates}
    report = []
    # autocommit: the memory reads events through agent_context (row-level security).
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        for scenario in scenarios:
            call = load_call(conn, scenario["call_id"])
            user = rebuild_memory(conn, call, settings.history_turns)
            system = rebuild_system(call["role"], call["system"])
            report.append(f"\n=== {scenario['id']} ({call['role']}, call {scenario['call_id']}): {scenario['note']}")
            for candidate in candidates:
                for attempt in range(1, repeat + 1):
                    result = run_one(client, candidate, call["role"], system, user)
                    marks = score(scenario, result) if result["valid"] else {"forbidden": [], "missing": [],
                                                                             "empty_sector": False}
                    t = totals[candidate]
                    t["runs"] += 1
                    t["valid"] += result["valid"]
                    t["forbidden"] += bool(marks["forbidden"])
                    t["missing"] += bool(marks["missing"])
                    t["empty"] += marks["empty_sector"]
                    t["tokens"] += result["tokens"]
                    t["cost"] += result["cost"]
                    t["seconds"] += result["seconds"]
                    flags = [name for name, on in (("FORBIDDEN", marks["forbidden"]), ("MISSING", marks["missing"]),
                                                   ("EMPTY-SECTOR", marks["empty_sector"]),
                                                   ("INVALID", not result["valid"])) if on]
                    report.append(f"--- {candidate} #{attempt} | {result['tokens']} tok | {result['seconds']:.1f} s"
                                  f" | {' '.join(flags) or 'ok'}")
                    report.append(f"    orders: {_order_list(result['orders'])}")
                    report.append(f"    words: {result['words'] or result.get('error', '')}")
                    print(f"{scenario['id']} {candidate} #{attempt}: {' '.join(flags) or 'ok'}", flush=True)

    summary = ["candidate | runs | valid | forbidden | missing expected | empty sector | avg tokens | avg s | total $"]
    for candidate, t in totals.items():
        runs = t["runs"] or 1
        summary.append(f"{candidate} | {t['runs']} | {t['valid']} | {t['forbidden']} | {t['missing']} | {t['empty']}"
                       f" | {t['tokens'] // runs} | {t['seconds'] / runs:.1f} | {t['cost']:.4f}")
    out_path.write_text("\n".join(summary + report) + "\n", encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main(sys.argv[1:])
