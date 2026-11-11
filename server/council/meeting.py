"""@brief The council meeting of one turn: ministers propose, the engine checks
the costs, the Chancellor composes a plan, the sovereign approves.

A meeting costs 3 model calls (4 once the Gastaldo sits, village block B+C);
each directive of the sovereign adds a new round of as many calls
(max_directives_per_turn rounds at most). Every call is
logged in model_calls, including failed ones and calls skipped because the
game's budget is exhausted.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from engine import check_plans, parse_order
from engine.market import MarketState, check_month_plan, market_status
from engine.turn import jobs_at_harvest
from engine.config import Config
from engine.orders import Order
from engine.state import GameState
from server.council import briefing, manual, memory, persons
from server.council.llm import LLMError
from server.council.personality import describe_traits, generate_traits
from server.council.settings import CouncilSettings
from server.db import games
from server.db.access import Clearance

PROMPTS_DIR = Path(__file__).with_name("prompts")
MINISTERS = ("treasurer", "architect")
# The Gastaldo joins the ministers when the realm's watchtower is finished
# (village block B+C): ministers_of(ctx) lists who sits this month.
GASTALDO = "gastaldo"
ROLE_ACTIONS = {
    "treasurer": ("set_tax", "set_ration", "hold_feast", "trade", "set_merchant_tax"),
    "architect": ("build", "assign_workers", "set_zones", "claim_tiles", "fell_forest", "demolish"),
    GASTALDO: ("set_militia", "set_doors"),
}
# Orders that exist only on the map: left out of the prompts of games
# without one (the engine would refuse them with NO_MAP anyway).
MAP_ACTIONS = ("set_zones", "claim_tiles", "fell_forest", "demolish")
# Likewise trade exists only where the realm can trade (a game with a market
# and, in village block A, a finished market building).
MARKET_ACTIONS = ("trade", "set_merchant_tax")
# The doors exist only in games with [migration] (village block B+C, stage 2).
MIGRATION_ACTIONS = ("set_doors",)
ROLE_TITLES = {"treasurer": "Treasurer", "architect": "Architect", "chancellor": "Chancellor", GASTALDO: "Gastaldo"}
ROLE_DUTIES = {
    "treasurer": "the treasury, taxes, food rations and feasts for the people.",
    # How to do the job well is the craft (prompts/expertise_<role>.txt),
    # not the duty: the duty only says what the office is for.
    "architect": "construction and the assignment of adults to fields, sawmills and quarries.",
    # On the map the Architect is also the town planner and keeps the land.
    "architect_map": "construction, the town plan and the realm's land (claiming, clearing, felling, "
                     "demolishing), and the assignment of adults to fields, sawmills, quarries and clearing.",
    "chancellor": "chairing the council: turning the ministers' proposals into one plan for the sovereign.",
    GASTALDO: "the village's gate and its guard: the militia against bandits, and what is seen of them "
              "and of the families who leave.",
}
LESSON_HINTS = {
    "chancellor": "You can also learn what the sovereign tends to approve, remove or ask for.",
}
MAX_PROPOSALS = 3
# Words the sovereign reads: the prompts ask for at most 120 (reports) and
# 150 (summary). A text far beyond, or a few words only, is refused and asked
# again like malformed JSON (game 21: a report of over a thousand words
# repeating its signature, and a summary of "..." with an empty plan).
MIN_TEXT_WORDS = 3  # "..." and "Petition check" were the short ones (games 20-21)
MAX_REPORT_WORDS = 300
MAX_SUMMARY_WORDS = 350

# Player-facing texts written by the server itself (the game is in Italian).
# The names also go into the prompts: "Architect" is neutral in English and
# the models would otherwise call the Architetta "l'architetto".
DISPLAY_NAMES = {"treasurer": "Il Tesoriere", "architect": "L'Architetta", "chancellor": "Il Cancelliere",
                 GASTALDO: "Il Gastaldo",
                 "square_voice": "La Voce della piazza", "people": "Il popolo"}
ABSENT_TEXT = "{name} non si è {presented} al consiglio questo mese."
BUDGET_TEXT = "Il fondo per i consiglieri è esaurito: {name} tace fino alla fine della partita."
FALLBACK_SUMMARY = (
    "{name} è assente. Gli scrivani hanno raccolto le proposte dei ministri: "
    "{accepted} su {total} superano il controllo dei costi e formano il piano."
)


class CouncilError(Exception):
    """Base of the errors the API turns into 409 Conflict."""


class NoOpenTurnError(CouncilError):
    pass


class MeetingAlreadyHeldError(CouncilError):
    pass


class NoMeetingYetError(CouncilError):
    pass


class TooManyDirectivesError(CouncilError):
    pass


class AlreadyApprovedError(CouncilError):
    pass


class CouncilUnreachableError(CouncilError):
    """The models could not be reached for any minister (network down, every
    call timed out): the meeting did not take place and may be held again."""


# Statuses of a call that never reached the model: no answer, no fault of it.
UNREACHABLE_STATUSES = ("http_error", "timeout")
UNREACHABLE_TEXT = ("Il consiglio non ha potuto riunirsi: i consiglieri non si raggiungono "
                    "(rete assente o nessuna risposta). Riprova tra poco: il mese non è perso.")


# JSON schemas sent to the models as the expected answer shape.
class _NoteSchema(BaseModel):
    to: Literal["treasurer", "architect", "chancellor", "gastaldo"]
    text: str


class _MinisterSchema(BaseModel):
    report: str
    proposals: list[Order]
    note: _NoteSchema | None = None  # secret note to one colleague (notes.py)


class _PlanItemSchema(BaseModel):
    proposer: Literal["treasurer", "architect", "gastaldo"]
    order: Order


class _ChancellorSchema(BaseModel):
    summary: str
    plan: list[_PlanItemSchema]
    note: _NoteSchema | None = None


class _LessonActionSchema(BaseModel):
    lesson: int
    action: Literal["confirm", "revise", "drop"]
    reason: str = ""  # before "text": models then tend to keep the two apart
    text: str = ""


class _LessonsSchema(BaseModel):
    actions: list[_LessonActionSchema]
    new_lessons: list[str]


# Loose models used to READ the answers: orders are checked one by one
# afterwards, so a single bad order does not throw away the whole reply.
class _MinisterReply(BaseModel):
    report: str
    proposals: list = []
    note: object = None  # checked by notes.store_note; a bad note never voids the reply


class _ChancellorReply(BaseModel):
    summary: str
    plan: list = []
    note: object = None


class _LessonsReply(BaseModel):
    # No defaults: a reply missing either key is invalid, not "no change".
    # Items are checked one by one by memory.split_revision.
    actions: list
    new_lessons: list[str]


@dataclass
class Actor:
    id: int
    role: str
    model: str
    traits: dict
    person: dict = field(default_factory=dict)  # name, gender, resume, salary (persons.py)


@dataclass
class MeetingContext:
    conn: psycopg.Connection
    client: object  # OpenRouterClient or FakeClient
    settings: CouncilSettings
    game_id: int
    realm_id: int
    realm_name: str
    turn: int
    state: GameState
    config: Config
    actors: dict[str, Actor]
    market: MarketState | None = None  # the warehouse at the start of this turn; None: no market


# ------------------------------------------------------------ model calls

def spent_usd(conn: psycopg.Connection, game_id: int) -> float:
    row = conn.execute(
        "SELECT coalesce(sum(cost_usd), 0) FROM model_calls WHERE game_id = %s", (game_id,)
    ).fetchone()
    return float(row[0])


REPLY_EXCERPT_CHARS = 2000
ERROR_CHARS = 500
PROMPT_CHARS = 20_000  # per prompt; about 10 MB per 120-turn game in total


def log_call(ctx: MeetingContext, actor: Actor, status: str, reply=None,
             error: str = "", keep_reply: bool = False, prompt: tuple[str, str] = ("", "")) -> None:
    """@brief One row per attempt. The raw reply is kept only when it was refused.
    @param prompt (system, user) as sent, for the admin view and debugging.
    """
    system, user = prompt
    ctx.conn.execute(
        "INSERT INTO model_calls (game_id, realm_id, actor_id, turn, model, input_tokens,"
        " output_tokens, cost_usd, latency_ms, status, error, reply_excerpt,"
        " prompt_system, prompt_user)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            ctx.game_id, ctx.realm_id, actor.id, ctx.turn, actor.model,
            reply.input_tokens if reply else 0,
            reply.output_tokens if reply else 0,
            reply.cost_usd if reply else 0,
            reply.latency_ms if reply else 0,
            status,
            error[:ERROR_CHARS],
            reply.text[:REPLY_EXCERPT_CHARS] if (reply and keep_reply) else "",
            system[:PROMPT_CHARS],
            user[:PROMPT_CHARS],
        ),
    )


def ask_text(ctx: MeetingContext, actor: Actor, system: str, user: str, max_chars: int) -> str:
    """@brief Plain-text call (private audience, Voice of the square); one
    retry on an empty answer.
    @return The answer cut to max_chars, or "" if none arrived.
    """
    for _attempt in range(2):
        if spent_usd(ctx.conn, ctx.game_id) >= ctx.settings.budget_usd_per_game:
            log_call(ctx, actor, "budget_exhausted", prompt=(system, user))
            return ""
        try:
            reply = ctx.client.complete(
                actor.role, actor.model, system, user, None,
                ctx.settings.reasoning_effort.get(actor.role),
            )
        except LLMError as error:
            log_call(ctx, actor, error.status, error=str(error), prompt=(system, user))
            return ""
        text = reply.text.strip()[:max_chars]
        if text:
            log_call(ctx, actor, "ok", reply, prompt=(system, user))
            return text
        log_call(ctx, actor, "invalid_reply", reply, error="empty answer", keep_reply=True,
                 prompt=(system, user))
    return ""


def _json_object(text: str) -> dict:
    """@brief Parse a reply, tolerating a ```json fence around it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    return data


RETRY_REMINDER = (
    "\n\n## Your previous answer was refused\n"
    "- Reason: {error}\n"
    "- Answer again, following the required JSON format and rules exactly."
)


def _refusal_reason(reply_text: str, reply_model: type[BaseModel],
                    extra_check: Callable[[BaseModel], str] | None) -> tuple[BaseModel | None, str]:
    """@brief Parse and check a reply. @return (parsed, "") or (None, why it is refused)."""
    try:
        parsed = reply_model.model_validate(_json_object(reply_text))
    except ValidationError as error:
        # Short form: field path + message of each problem, without the input dump.
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
        return None, f"wrong JSON shape: {problems}"
    except ValueError as error:
        return None, f"not a JSON object: {error}"
    if extra_check is not None:
        rule_error = extra_check(parsed)
        if rule_error:
            return None, rule_error
    return parsed, ""


def _ask(ctx: MeetingContext, actor: Actor, system: str, user: str,
         schema: dict, reply_model: type[BaseModel],
         extra_check: Callable[[BaseModel], str] | None = None,
         annotate: Callable[[BaseModel], str] | None = None) -> tuple[BaseModel | None, str]:
    """@brief Call the model with one retry on an invalid reply. The retry tells
    the model why its first answer was refused.
    @param extra_check Optional rule check on the parsed reply; a non-empty
           message makes the reply invalid (and retried) like a JSON error.
    @param annotate Optional note on an ACCEPTED reply (e.g. parts discarded),
           stored in the error column of its "ok" row for debugging.
    @return (parsed reply, "ok") or (None, reason) with reason in
            budget_exhausted, timeout, http_error, invalid_reply.
    """
    prompt = user
    effort = ctx.settings.reasoning_effort.get(actor.role)
    for _attempt in range(2):
        if spent_usd(ctx.conn, ctx.game_id) >= ctx.settings.budget_usd_per_game:
            log_call(ctx, actor, "budget_exhausted", prompt=(system, prompt))
            return None, "budget_exhausted"
        try:
            reply = ctx.client.complete(actor.role, actor.model, system, prompt, schema, effort)
        except LLMError as error:
            log_call(ctx, actor, error.status, error=str(error), prompt=(system, prompt))
            return None, error.status  # no retry: a timeout would double the wait
        parsed, refusal = _refusal_reason(reply.text, reply_model, extra_check)
        if parsed is None:
            log_call(ctx, actor, "invalid_reply", reply, error=refusal, keep_reply=True,
                     prompt=(system, prompt))
            prompt = user + RETRY_REMINDER.format(error=refusal)
            if reply.output_tokens >= ctx.settings.output_cap(actor.role):
                # It ran up to the output cap (reasoning that never ended, or a
                # looping string: 5 of 6 refusals in games 5-7). The model has
                # no reasoning budget, only levels: retry without reasoning, or
                # at the lowest level where reasoning cannot be turned off (game
                # 20: GLM 5.3 Flash answered "none" with HTTP 400, and the
                # Architect missed the meeting).
                effort = "low" if actor.model in ctx.settings.models_reasoning_required else "none"
            continue
        note = annotate(parsed) if annotate else ""
        log_call(ctx, actor, "ok", reply, error=note, prompt=(system, prompt))
        return parsed, "ok"
    return None, "invalid_reply"


# ------------------------------------------------------- order validation

def _check_order(role: str, raw_order: object) -> tuple[dict | None, str]:
    """@brief Parse one proposed order and check it belongs to the role.
    @return (clean order dict, "") or (None, reason).
    """
    order, code, _message = parse_order(raw_order)
    if order is None:
        return None, code
    if order.action not in ROLE_ACTIONS.get(role, ()):
        return None, "NOT_ROLE_ACTION"
    return order.model_dump(exclude={"priority"}, exclude_none=True), ""


def _validate_proposals(role: str, raw_proposals: list) -> tuple[list[dict], list[dict]]:
    valid, discarded = [], []
    for index, raw_order in enumerate(raw_proposals):
        if index >= MAX_PROPOSALS:
            discarded.append({"order": raw_order, "reason": "TOO_MANY_PROPOSALS"})
            continue
        clean_order, reason = _check_order(role, raw_order)
        if clean_order is None:
            discarded.append({"order": raw_order, "reason": reason})
        else:
            valid.append(clean_order)
    return valid, discarded


def _validate_plan(raw_plan: list, ministers: tuple[str, ...] = MINISTERS) -> tuple[list[dict], list[dict]]:
    """@param ministers Who sits this month (ministers_of): a plan item of an
           absent office (a Gastaldo before the watchtower) is discarded."""
    plan, discarded = [], []
    for item in raw_plan:
        proposer = item.get("proposer") if isinstance(item, dict) else None
        raw_order = item.get("order") if isinstance(item, dict) else item
        if proposer not in ministers:
            discarded.append({"item": item, "reason": "UNKNOWN_PROPOSER"})
            continue
        clean_order, reason = _check_order(proposer, raw_order)
        if clean_order is None:
            discarded.append({"item": item, "reason": reason})
        else:
            plan.append({"proposer": proposer, "order": clean_order})
    return plan, discarded


def _changes_nothing(state: GameState, order: dict) -> bool:
    """@brief An order that only repeats what is already in force."""
    action = order["action"]
    if action == "set_tax":
        return order["rate"] == state.tax_rate
    if action == "set_ration":
        return order["ration"] == state.ration
    if action == "set_doors":
        return order["doors"] == state.doors
    if action == "assign_workers":
        workers = state.workers
        return ((order["food"], order["wood"], order["stone"], order.get("clearing", 0))
                == (workers.food, workers.wood, workers.stone, workers.clearing))
    return False


def _drop_no_change(state: GameState, plan: list[dict]) -> tuple[list[dict], list[dict]]:
    """@brief Keep useless orders out of the plan the sovereign reads (they
    were in most plans of games 1 and 2: set_tax 10 with taxes at 10%)."""
    kept, dropped = [], []
    for item in plan:
        if _changes_nothing(state, item["order"]):
            dropped.append({"item": item, "reason": "NO_CHANGE"})
        else:
            kept.append(item)
    return kept, dropped


def _run_check(ctx: MeetingContext, items: list[dict]) -> dict:
    """@brief Engine dry run of a list of {proposer, order}: trades first, as
    the month runs them, then the rest in list order; one verdict per item."""
    orders = [parse_order(item["order"])[0] for item in items]
    report = check_month_plan(ctx.state, orders, ctx.market, ctx.config, str(ctx.realm_id))
    verdicts = [
        {"accepted": result.accepted, "code": result.code, "message": result.message}
        for result in report.results
    ]
    return {"verdicts": verdicts, "spent": report.spent, "remaining": report.remaining}


def _idle_beyond_jobs(order: dict, jobs: dict[str, int]) -> str:
    """@brief Warning for an assignment that puts workers where no job waits
    (legal, but they produce nothing); "" when every worker has a job."""
    if order["action"] != "assign_workers":
        return ""
    excess = [f"{order[s] - jobs[s]} {s} workers beyond the {jobs[s]} jobs"
              for s in ("food", "wood", "stone") if order[s] > jobs[s]]
    return ("; WARNING: " + ", ".join(excess) + " would produce nothing") if excess else ""


def _idle_left(order: dict, adults: int) -> str:
    """@brief Warning for an assignment that leaves adults without work.

    Why: gpt-oss read assign_workers as a change ("food 0 wood 1 stone 0" to
    send one idle adult to the sawmill), which would empty the fields; the
    numbers are totals, and a big idle count shows the misreading.
    """
    if order["action"] != "assign_workers":
        return ""
    # Merchants (block A) were missing here: a market's workers read as idle.
    idle = adults - order["food"] - order["wood"] - order["stone"] - order.get("clearing", 0) - order.get("trade", 0)
    return f"; WARNING: {idle} adults would be left without work" if idle > 0 else ""


def _clearing_without_land(order: dict, state: GameState) -> str:
    """@brief Warning for clearing workers with nothing queued (they would idle)."""
    if order["action"] != "assign_workers" or not order.get("clearing") or state.clearing_queue:
        return ""
    return (f"; WARNING: {order['clearing']} clearing workers but nothing is queued for clearing"
            " (unless a claim or a felling in this plan queues it)")


def _check_lines(ctx: MeetingContext, items: list[dict], check: dict) -> list[str]:
    jobs = jobs_at_harvest(ctx.state, ctx.config)
    lines = []
    for item, verdict in zip(items, check["verdicts"]):
        outcome = "affordable" if verdict["accepted"] else f"REJECTED {verdict['code']}: {verdict['message']}"
        outcome += (_idle_beyond_jobs(item["order"], jobs) + _idle_left(item["order"], ctx.state.free_adults())
                    + _clearing_without_land(item["order"], ctx.state))
        lines.append(f"{item['proposer']} {json.dumps(item['order'])}: {outcome}")
    lines.append(f"Spent if all accepted ones run: {check['spent']}; left: {check['remaining']}")
    return lines


# --------------------------------------------------------------- prompts

def render_prompt(name: str, **values) -> str:
    return (PROMPTS_DIR / name).read_text().format(**values)


# The rule about trade in every prompt: games without a market keep the
# rule of the playtests (game 2: the council believed gold buys food); in
# village block A a realm without its market building is told so.
MARKET_RULES = {
    "council": {
        "none": "- There is no market and no trade yet: gold cannot buy food, wood or stone. Food comes only from "
                "the farms. A feast costs gold and only lifts the people's mood for a while; it brings no food.",
        "unbuilt": "- The realm has no market yet: until its market building is finished (the Architect builds "
                   "it, see market in the manual), gold cannot buy food, wood or stone and nobody here knows the "
                   "prices. Food comes only from the farms. A feast costs gold and only lifts the people's mood "
                   "for a while; it brings no food.",
        "open": "- There is a common market shared with the other realms: only the Treasurer buys and sells food, "
                "wood and stone there, at the prices in the briefing, within the lots the merchants can handle "
                "(see Market in the manual). A feast costs gold and only lifts the people's mood for a while; it "
                "brings no food.",
    },
    "lessons": {
        "none": "- There is no market yet: gold cannot buy food, and a feast brings no food; do not learn otherwise.",
        "unbuilt": "- The realm has no market until its market building is finished: gold cannot buy food before "
                   "then, and a feast brings no food; do not learn otherwise.",
        "open": "- Gold buys at the market only what the other realms put on sale, and a feast brings no food; do "
                "not learn otherwise.",
    },
    "mandate": {
        "none": "there is no market or trade, gold cannot buy food",
        "unbuilt": "the realm has no market yet: no trade until the Architect's market building is finished",
        "open": "trade happens only through the Treasurer's trade orders at the common market",
    },
}


def market_rule(config: Config, kind: str, state: GameState | None = None) -> str:
    """@brief The trade rule of a prompt kind ("council", "lessons", "mandate").
    @param state The realm's state; None reads the game alone (open if it has a market)."""
    if state is None:
        status = "open" if config.market is not None else "none"
    else:
        status = market_status(state, config)
    return MARKET_RULES[kind][status]


def _village_market(config: Config) -> bool:
    """@brief True in games where the market is a building (village block A)."""
    return config.market is not None and config.market.needs_building


def _order_formats(ctx: MeetingContext) -> str:
    text = render_prompt("order_formats.txt", max_tax_rate=ctx.config.economy.max_tax_rate)
    status = market_status(ctx.state, ctx.config)
    if status == "open":
        text += render_prompt("order_formats_market.txt", lot=ctx.config.market.lot_units)
    if _village_market(ctx.config):
        text += render_prompt("order_formats_village.txt")
        if status == "open":
            text += render_prompt("order_formats_merchant_tax.txt", max_rate=ctx.config.market.max_merchant_tax)
    if ctx.config.map is not None:
        text += render_prompt("order_formats_map.txt", max_claim=ctx.config.map.claim_max_per_order)
    if ctx.config.bandits is not None:  # village block B+C
        text += render_prompt("order_formats_watchtower.txt")
        if GASTALDO in ctx.actors:
            text += render_prompt("order_formats_militia.txt")
            if ctx.config.migration is not None:  # stage 2
                text += render_prompt("order_formats_doors.txt",
                                      closed_min_guards=ctx.config.migration.closed_min_guards)
    return text


def allowed_actions(ctx: MeetingContext, role: str) -> str:
    status = market_status(ctx.state, ctx.config)
    actions = [a for a in ROLE_ACTIONS[role] if (ctx.config.map is not None or a not in MAP_ACTIONS)
               and (status == "open" or a not in MARKET_ACTIONS)
               and (a != "set_merchant_tax" or _village_market(ctx.config))
               and (ctx.config.migration is not None or a not in MIGRATION_ACTIONS)]
    return ", ".join(actions)


def duties_of(ctx: MeetingContext, role: str) -> str:
    duties = ROLE_DUTIES[role]
    if role == "architect" and ctx.config.map is not None:
        duties = ROLE_DUTIES["architect_map"]
    if _village_market(ctx.config) and role in VILLAGE_DUTIES:
        duties += VILLAGE_DUTIES[role]
    if ctx.config.migration is not None and role == GASTALDO:
        duties += DOORS_DUTY
    return duties


# Village block A: the market is a building, its merchants pay their own tax.
VILLAGE_DUTIES = {
    "architect": " Also the realm's market building and the merchants who work in it.",
    "treasurer": " Also the merchants' tax, once the realm has a market.",
}
# Village block B+C, stage 2: the Gastaldo keeps the doors too.
DOORS_DUTY = " Also the doors: who of the wanderers may settle in the realm."


EXPERTISE_INTRO = (
    "These are the habits of your craft, learned before you entered the council: good practice, not laws. "
    "Weigh them against the facts of the month and follow them as your own outlook leads you: a bold person "
    "may build or spend sooner, a cautious one later, an ambitious one may favour other aims. How well you "
    "apply them depends on your competence.\n"
)


def role_expertise(ctx: MeetingContext, role: str) -> str:
    """@brief The craft of a role in this realm: town planning on the map,
    trading once the realm can trade, the village market where it is a building,
    the doors where newcomers can settle (stage 2)."""
    return expertise_block(role, ctx.config.map is not None, market_status(ctx.state, ctx.config) == "open",
                           _village_market(ctx.config), ctx.config.migration is not None)


def expertise_block(role: str, with_map: bool = False, with_market: bool = False, with_village: bool = False,
                    with_doors: bool = False) -> str:
    """@brief What the office's training teaches (a role's craft, the same
    for every holder today; later it can differ by person, in a résumé).
    On the map the Architect's craft adds town planning (expertise_<role>_map.txt);
    with a market the Treasurer's adds trading (expertise_<role>_market.txt)."""
    path = PROMPTS_DIR / f"expertise_{role}.txt"
    if not path.exists():
        return ""
    text = path.read_text()
    for wanted, suffix in ((with_map, "map"), (with_market, "market"), (with_village, "village"),
                           (with_doors, "doors")):
        extra = PROMPTS_DIR / f"expertise_{role}_{suffix}.txt"
        if wanted and extra.exists():
            text += extra.read_text()
    return EXPERTISE_INTRO + text


def _person(ctx: MeetingContext, role: str) -> dict:
    return ctx.actors[role].person if role in ctx.actors else {}


def name_of(ctx: MeetingContext, role: str) -> str:
    """@brief How the game calls this office's holder ("Gisella da Valle,
    l'Architetta"; the bare title for games without persons)."""
    person = ctx.actors[role].person if role in ctx.actors else {}
    return persons.display_name(role, person)


def ministers_of(ctx: MeetingContext) -> tuple[str, ...]:
    """@brief The ministers who sit this month: the Gastaldo too once it has come."""
    return (*MINISTERS, GASTALDO) if GASTALDO in ctx.actors else MINISTERS


def names_by_role(ctx: MeetingContext) -> dict[str, str]:
    return {role: name_of(ctx, role) for role in (*ministers_of(ctx), "chancellor", "square_voice", "people")}


def names_by_actor(ctx: MeetingContext) -> dict[int, str]:
    return {a.id: name_of(ctx, a.role) for a in ctx.actors.values()}


def person_block(actor: Actor) -> str:
    return persons.person_lines(actor.role, actor.person)


def mandate_block(ctx: MeetingContext, actor: Actor) -> str:
    """@brief The approved mandate lines for this actor's prompt ("" if none)."""
    from server.council import mandates  # the mandates module builds on this one
    return mandates.prompt_block(ctx, actor)


def _minister_system(ctx: MeetingContext, actor: Actor) -> str:
    return render_prompt(
        "minister_system.txt",
        mandate=mandate_block(ctx, actor),
        manual=manual.prompt_text(ctx.config),
        expertise=role_expertise(ctx, actor.role),
        role_title=ROLE_TITLES[actor.role],
        display_name=name_of(ctx, actor.role),
        person=person_block(actor),
        realm_name=ctx.realm_name,
        duties=duties_of(ctx, actor.role),
        traits=describe_traits(actor.traits),
        allowed_actions=allowed_actions(ctx, actor.role),
        language=ctx.settings.language,
        order_formats=_order_formats(ctx),
        market_rule=market_rule(ctx.config, "council", ctx.state),
        note_roles=_or_list([f'"{role}"' for role in (*ministers_of(ctx), "chancellor")]),
    )


def _or_list(items: list[str]) -> str:
    """@brief "a or b", "a, b or c": the wording the prompts always had."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def _minister_names(ctx: MeetingContext) -> str:
    """@brief '"Name, il Tesoriere" (a man) and "..." (a woman)', one per sitting minister."""
    names = [f'"{name_of(ctx, role)}" ({persons.GENDER_WORDS[persons.gender_of(role, _person(ctx, role))]})'
             for role in ministers_of(ctx)]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _chancellor_system(ctx: MeetingContext, actor: Actor) -> str:
    sitting = ministers_of(ctx)
    return render_prompt(
        "chancellor_system.txt",
        mandate=mandate_block(ctx, actor),
        manual=manual.prompt_text(ctx.config),
        expertise=role_expertise(ctx, actor.role),
        realm_name=ctx.realm_name,
        traits=describe_traits(actor.traits),
        minister_names=_minister_names(ctx),
        person=person_block(actor),
        plan_roles=_or_list([f"{role} ({allowed_actions(ctx, role)})" for role in sitting]),
        proposer_options=_or_list([f'"{role}"' for role in sitting]),
        note_roles=_or_list([f'"{role}"' for role in (*sitting, "chancellor")]),
        language=ctx.settings.language,
        order_formats=_order_formats(ctx),
        market_rule=market_rule(ctx.config, "council", ctx.state),
    )


# ------------------------------------------------------------- storage

def insert_message(ctx: MeetingContext, round_number: int, kind: str,
                   speaker: Actor | None, content: str, payload: dict,
                   visibility: str = "council") -> None:
    ctx.conn.execute(
        "INSERT INTO council_messages (game_id, realm_id, turn, speaker_actor_id, content,"
        " visibility, kind, round, payload) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (ctx.game_id, ctx.realm_id, ctx.turn, speaker.id if speaker else None,
         content, visibility, kind, round_number, Jsonb(payload)),
    )


def _people_kwargs(ctx: MeetingContext) -> dict:
    choice, lines = people_this_month(ctx)
    return {"people": choice, "people_lines": lines}


def people_this_month(ctx: MeetingContext) -> tuple[object, list[str]]:
    """@brief The people's choice for the open turn (for the harvest estimate)
    and what the council may know of it: the behaviour in words and the
    petition, which is public. Empty when the people decided nothing."""
    from server.council import people  # the people module builds on this one
    choice = games.load_people_choice(ctx.conn, ctx.realm_id, ctx.turn)
    decisions = people.recent_decisions(ctx.conn, ctx.realm_id, ctx.turn, ctx.turn)
    if not decisions:
        return None, []
    lines = ["## The people this month"] + people.decision_lines(decisions, ctx.turn)
    petition = decisions[0]["petition"]
    if petition and decisions[0]["answer"] is None:
        lines.append(f"- If the sovereign grants the petition, this order runs first: "
                     f"{memory.order_text(petition)}. Advise the sovereign on it.")
    return choice, lines


SQUARE_MEMORY_TURNS = 3  # turns of the square's words in each council briefing


def square_voices(ctx: MeetingContext, first_turn: int | None = None) -> list[tuple[int, str]]:
    """@brief What the square said from first_turn to this turn, oldest first.
    The council has no mood number: these words are all it knows of the
    people, so several months are kept (a silent month leaves the others).
    @param first_turn Default: the last SQUARE_MEMORY_TURNS turns.
    """
    if first_turn is None:
        first_turn = ctx.turn - SQUARE_MEMORY_TURNS + 1
    rows = ctx.conn.execute(
        "SELECT turn, content FROM council_messages WHERE realm_id = %s AND kind = 'voice'"
        " AND turn >= %s AND turn <= %s ORDER BY id",
        (ctx.realm_id, first_turn, ctx.turn),
    ).fetchall()
    return list(dict(rows).items())  # one per turn: the latest wins


def _history(ctx: MeetingContext, actor: Actor, turns_back: int) -> list[str]:
    """@brief Free memory: the actor's proposals (or plans) of the last turns and what followed."""
    if actor.role == "chancellor":
        return memory.chancellor_consequence_lines(
            ctx.conn, ctx.game_id, ctx.realm_id, actor.id,
            ctx.turn - turns_back, ctx.turn, names_by_role(ctx),
        )
    return memory.consequence_lines(
        ctx.conn, ctx.game_id, ctx.realm_id, actor.id, actor.role,
        ctx.turn - turns_back, ctx.turn, names_by_actor(ctx),
    )


def _audience_memory(ctx: MeetingContext, actor: Actor) -> tuple[list[str], list[str]]:
    """@brief (own private dialogue of recent turns, facts about the others')."""
    dialogue = memory.audience_dialogue(
        ctx.conn, actor.id, ctx.turn - memory.AUDIENCE_HISTORY_TURNS, ctx.turn
    )
    actor_names = names_by_actor(ctx)
    facts = memory.audience_facts(ctx.conn, ctx.realm_id, ctx.turn, actor.id, actor_names)
    return dialogue, facts


def _note_lines(ctx: MeetingContext, actor: Actor, last_turn: int | None = None) -> list[str]:
    """@brief This actor's secret notes of recent turns; a note is read the
    month after it was written (last_turn defaults to the previous turn)."""
    from server.council import notes  # kept apart: only the two ends ever read a note
    actor_names = names_by_actor(ctx)
    last = ctx.turn - 1 if last_turn is None else last_turn
    return notes.note_lines(ctx.conn, actor.id, last - notes.NOTE_HISTORY_TURNS + 1, last, actor_names)


def _store_note(ctx: MeetingContext, actor: Actor, raw: object) -> None:
    from server.council import notes
    notes.store_note(ctx.conn, ctx.game_id, ctx.realm_id, ctx.turn, ctx.actors, actor, raw)


def _directives(ctx: MeetingContext) -> list[str]:
    return [row[0] for row in ctx.conn.execute(
        "SELECT content FROM council_messages WHERE realm_id = %s AND turn = %s"
        " AND kind = 'directive' ORDER BY id",
        (ctx.realm_id, ctx.turn),
    )]


# ------------------------------------------------------------- lessons

SEASON_TURNS = 3


def is_reflection_turn(turn: int) -> bool:
    """@brief First turn of a season after the first one: 4, 7, 10, ..."""
    return turn > 1 and (turn - 1) % SEASON_TURNS == 0


def _lessons_system(ctx: MeetingContext, actor: Actor) -> str:
    return render_prompt(
        "lessons_system.txt",
        mandate=mandate_block(ctx, actor),
        manual=manual.prompt_text(ctx.config),
        expertise=role_expertise(ctx, actor.role),
        role_title=ROLE_TITLES[actor.role],
        display_name=name_of(ctx, actor.role),
        person=person_block(actor),
        realm_name=ctx.realm_name,
        duties=duties_of(ctx, actor.role),
        traits=describe_traits(actor.traits),
        language=ctx.settings.language,
        max_lessons=ctx.settings.max_lessons,
        role_hint=LESSON_HINTS.get(actor.role, ""),
        market_rule=market_rule(ctx.config, "lessons", ctx.state),
    )


def _reflected_this_turn(ctx: MeetingContext, actor: Actor) -> bool:
    """@brief A meeting held again after a crash must not review twice."""
    return ctx.conn.execute(
        "SELECT 1 FROM lessons WHERE actor_id = %s AND (origin_turn = %s OR status_turn = %s"
        " OR last_confirmed_turn = %s) LIMIT 1",
        (actor.id, ctx.turn, ctx.turn, ctx.turn),
    ).fetchone() is not None


def _reflect(ctx: MeetingContext, actor: Actor) -> None:
    """@brief End-of-season reflection: confirm, revise, drop or add secret lessons.
    On failure the lessons stay exactly as they were.
    """
    if _reflected_this_turn(ctx, actor):
        return
    season = _history(ctx, actor, SEASON_TURNS)
    lessons = memory.current_lessons(ctx.conn, actor.id)
    if not season and not lessons:
        return  # nothing to reflect on: save the call
    numbered = [f"{number}. {memory.lesson_line(lesson)}" for number, lesson in enumerate(lessons, 1)]
    audiences = memory.audience_dialogue(ctx.conn, actor.id, ctx.turn - SEASON_TURNS, ctx.turn - 1)
    # Runs before this turn's Voice speaks: the season's square is turns T-3..T-1.
    square = briefing.square_lines(square_voices(ctx, ctx.turn - SEASON_TURNS))
    user = "\n".join(
        ["## What happened this season"] + [f"- {entry}" for entry in season or ["You did nothing."]]
        + square + _note_lines(ctx, actor)
        + (["## Your private audiences with the sovereign this season"]
           + [f"- {line}" for line in audiences] if audiences else [])
        + ["## Your current lessons"] + (numbered or ["None yet."])
    )

    accepted = {}

    def discarded_note(reply: _LessonsReply) -> str:
        actions, new_lessons, discarded = memory.split_revision(
            lessons, reply.actions, reply.new_lessons, ctx.settings.max_lessons)
        accepted.update(actions=actions, new_lessons=new_lessons)
        return ("discarded: " + "; ".join(discarded)) if discarded else ""

    # Only malformed JSON is retried; a bad action is discarded on its own.
    reply, _status = _ask(ctx, actor, _lessons_system(ctx, actor), user,
                          _LessonsSchema.model_json_schema(), _LessonsReply, annotate=discarded_note)
    if reply is not None:
        memory.apply_revision(ctx.conn, ctx.game_id, ctx.realm_id, actor.id, ctx.turn,
                              lessons, accepted["actions"], accepted["new_lessons"])


# --------------------------------------------------------------- rounds

def _absence_text(ctx: MeetingContext, role: str, reason: str) -> str:
    template = BUDGET_TEXT if reason == "budget_exhausted" else ABSENT_TEXT
    person = ctx.actors[role].person if role in ctx.actors else {}
    presented = "presentata" if persons.gender_of(role, person) == "f" else "presentato"
    return template.format(name=name_of(ctx, role), presented=presented)


def _minister_turn(ctx: MeetingContext, actor: Actor, round_number: int,
                   events: list[dict], directives: list[str]) -> tuple[str, list[dict], dict]:
    """@brief One minister speaks. The report is stored by the caller, once the
    round is known to take place.
    @return (report text, valid proposals, message payload)."""
    user = briefing.minister_briefing(
        actor.role, ctx.state, ctx.config, events,
        _history(ctx, actor, ctx.settings.history_turns), directives,
        [memory.lesson_line(lesson) for lesson in memory.current_lessons(ctx.conn, actor.id)],
        *_audience_memory(ctx, actor),
        square_voices=square_voices(ctx), **_people_kwargs(ctx), note_lines=_note_lines(ctx, actor),
        market=briefing.market_lines(ctx.state, ctx.config, ctx.market, str(ctx.realm_id))
        if actor.role == "treasurer" else (),
        gate=gate_lines(ctx) if actor.role == GASTALDO else (),
    )
    schema = _MinisterSchema.model_json_schema()
    system = _minister_system(ctx, actor)
    reply, status = _ask(ctx, actor, system, user, schema, _MinisterReply, extra_check=_report_length)
    if reply is None:
        report, valid, discarded = _absence_text(ctx, actor.role, status), [], []
    else:
        valid, discarded = _validate_proposals(actor.role, reply.proposals)
        reply, valid, discarded = _retry_bad_zones(ctx, actor, system, user, reply, valid, discarded)
        report = reply.report
        _store_note(ctx, actor, reply.note)
    payload = {"proposals": valid, "discarded": discarded, "absent": reply is None, "status": status}
    return report, valid, payload


def gate_lines(ctx: MeetingContext) -> list[str]:
    """@brief The Gastaldo's section, with the realm's own raids, flights and
    arrivals of the last months (read as the server: they are the realm's own events)."""
    rows = ctx.conn.execute(
        "SELECT turn, kind, data FROM events WHERE realm_id = %s AND kind IN ('raid', 'flight', 'arrival')"
        " AND turn >= %s AND turn < %s ORDER BY turn, id",
        (ctx.realm_id, ctx.turn - briefing.GATE_MEMORY_TURNS, ctx.turn),
    ).fetchall()
    return briefing.gate_lines(ctx.state, ctx.config, rows)


def _length_refusal(text: str, max_words: int) -> str:
    """@brief Why a text the sovereign reads is refused for its length, or ""."""
    words = len(text.split())
    if words < MIN_TEXT_WORDS:
        return f"the text has {words} words: write a real report to the sovereign"
    if words > max_words:
        return f"the text has {words} words, far over the limit: keep to the asked length and do not repeat yourself"
    return ""


def _report_length(reply) -> str:
    return _length_refusal(reply.report, MAX_REPORT_WORDS)


def _summary_length(reply) -> str:
    return _length_refusal(reply.summary, MAX_SUMMARY_WORDS)


def _zones_refusal(ctx: MeetingContext, proposals: list[dict]) -> str:
    """@brief Why the proposed town plan would be refused by the engine, or ""."""
    for order in proposals:
        if order["action"] == "set_zones":
            result = check_plans(ctx.state, [parse_order(order)[0]], ctx.config).results[0]
            if not result.accepted:
                return result.message
    return ""


def _retry_bad_zones(ctx: MeetingContext, actor: Actor, system: str, user: str, reply,
                     valid: list[dict], discarded: list[dict]) -> tuple:
    """@brief A town plan the engine would refuse gets one more try, with the
    reason; if the second plan fails too, only the plan is dropped and the
    rest of the reply stays (lab/urban_probe.py: about 1 plan in 3 fails).
    @return (reply, valid proposals, discarded proposals).
    """
    refusal = _zones_refusal(ctx, valid)
    if not refusal:
        return reply, valid, discarded
    retry_user = user + RETRY_REMINDER.format(error=f"your town plan (set_zones) would be refused: {refusal}")
    second, _status = _ask(ctx, actor, system, retry_user, _MinisterSchema.model_json_schema(), _MinisterReply,
                           extra_check=_report_length)
    if second is not None:
        reply = second
        valid, discarded = _validate_proposals(actor.role, second.proposals)
        refusal = _zones_refusal(ctx, valid)
    if refusal:
        discarded = discarded + [{"order": o, "reason": "BAD_ZONES"} for o in valid if o["action"] == "set_zones"]
        valid = [o for o in valid if o["action"] != "set_zones"]
    return reply, valid, discarded


def _chancellor_turn(ctx: MeetingContext, round_number: int, events: list[dict],
                     directives: list[str], reports: dict[str, str], proposals: list[dict]) -> None:
    check = _run_check(ctx, proposals)
    actor = ctx.actors.get("chancellor")
    reply, status = None, "missing"
    if actor is not None:
        lessons = [memory.lesson_line(lesson) for lesson in memory.current_lessons(ctx.conn, actor.id)]
        user = briefing.chancellor_briefing(
            ctx.state, ctx.config, events, directives, reports, proposals,
            _check_lines(ctx, proposals, check), lessons, *_audience_memory(ctx, actor),
            square_voices=square_voices(ctx), **_people_kwargs(ctx), note_lines=_note_lines(ctx, actor),
            market=briefing.market_summary_line(ctx.config, ctx.market, ctx.state),
            gate=gate_lines(ctx) if GASTALDO in ctx.actors else (),
        )
        schema = _ChancellorSchema.model_json_schema()
        reply, status = _ask(ctx, actor, _chancellor_system(ctx, actor), user, schema, _ChancellorReply,
                             extra_check=_summary_length)
    if reply is None:
        # Fixed-template fallback: the plan is every proposal that passes the check.
        plan = [item for item, verdict in zip(proposals, check["verdicts"]) if verdict["accepted"]]
        office = name_of(ctx, "chancellor")
        summary = FALLBACK_SUMMARY.format(name=office[0].upper() + office[1:], accepted=len(plan), total=len(proposals))
        discarded = []
    else:
        plan, discarded = _validate_plan(reply.plan, ministers_of(ctx))
        summary = reply.summary
        _store_note(ctx, actor, reply.note)
    plan, no_change = _drop_no_change(ctx.state, plan)
    discarded += no_change
    payload = {"plan": plan, "discarded": discarded, "absent": reply is None,
               "status": status, "check": _run_check(ctx, plan)}
    insert_message(ctx, round_number, "summary", actor, summary, payload)


def _run_round(ctx: MeetingContext, round_number: int) -> None:
    events = games.list_visible_events(
        ctx.conn, ctx.game_id, ctx.realm_id, ctx.turn - 1, Clearance.COUNCIL
    )
    directives = _directives(ctx)
    reports, proposals, spoken = {}, [], []
    for role in ministers_of(ctx):
        actor = ctx.actors.get(role)
        if actor is None:
            continue
        report, valid, payload = _minister_turn(ctx, actor, round_number, events, directives)
        reports[role] = report
        proposals += [{"proposer": role, "order": order} for order in valid]
        spoken.append((actor, report, payload))
    # Why: game 34, a network outage left every minister "absent" and the month
    # resolved with an empty plan. The first round stops before anything of it
    # is stored, so the meeting can be held again (_rounds_held stays 0).
    # Directive rounds are not stopped: their directive is already stored.
    if round_number == 1 and spoken and all(
            payload["status"] in UNREACHABLE_STATUSES for _, _, payload in spoken):
        raise CouncilUnreachableError(UNREACHABLE_TEXT)
    for actor, report, payload in spoken:
        insert_message(ctx, round_number, "report", actor, report, payload)
    _chancellor_turn(ctx, round_number, events, directives, reports, proposals)


# ------------------------------------------------------------ public API

def load_context(conn: psycopg.Connection, realm_id: int, client, settings) -> MeetingContext:
    row = conn.execute(
        "SELECT r.game_id, r.name, t.number FROM realms r"
        " JOIN turns t ON t.game_id = r.game_id AND t.status = 'open' WHERE r.id = %s",
        (realm_id,),
    ).fetchone()
    if row is None:
        raise NoOpenTurnError(f"realm {realm_id} has no open turn")
    game_id, realm_name, turn = row
    actors = {
        role: Actor(actor_id, role, model, personality.get("traits", {}), personality)
        for actor_id, role, model, personality in conn.execute(
            "SELECT id, role, model, personality FROM actors WHERE realm_id = %s", (realm_id,)
        )
    }
    return MeetingContext(
        conn, client, settings, game_id, realm_id, realm_name, turn,
        games.load_latest_state(conn, realm_id), games.load_game_config(conn, game_id), actors,
        games.load_market(conn, game_id, turn),
    )


def _has_watchtower(state: GameState) -> bool:
    return any(b.kind == "watchtower" and b.turns_left == 0 for b in state.buildings)


def ensure_gastaldo(ctx: MeetingContext) -> None:
    """@brief Seat the Gastaldo at the first meeting after the watchtower is
    finished (village block B+C). The engine already pays its salary (the
    watchtower adds [bandits] gastaldo_salary); here the person joins: a free
    moderate of the catalogue in games with persons, else a plain office with
    the treasurer's model, as the councils of games without persons."""
    if GASTALDO in ctx.actors or ctx.config.bandits is None or not _has_watchtower(ctx.state):
        return
    seed = ctx.conn.execute("SELECT seed FROM games WHERE id = %s", (ctx.game_id,)).fetchone()[0]
    model = ctx.settings.models.get(GASTALDO) or ctx.actors["treasurer"].model
    personality = {"traits": generate_traits(seed, ctx.realm_id, GASTALDO)}
    if any(actor.person.get("persona") for actor in ctx.actors.values()):
        taken = {row[0] for row in ctx.conn.execute(
            "SELECT a.personality->>'persona' FROM actors a JOIN realms r ON r.id = a.realm_id"
            " WHERE r.game_id = %s AND a.personality ? 'persona'", (ctx.game_id,))}
        try:
            person = persons.draw_person(persons.load_catalog(), GASTALDO, seed, ctx.realm_id, taken)
        except ValueError:
            person = None  # more realms than gastaldi in the catalogue: a plain office
        if person is not None:
            model = ctx.settings.model_tiers[person["tier"]]
            personality = {key: person[key] for key in ("traits", "name", "gender", "resume", "salary", "tier")}
            personality["persona"] = person["id"]
    actor_id = ctx.conn.execute(
        "INSERT INTO actors (realm_id, role, model, personality) VALUES (%s, %s, %s, %s) RETURNING id",
        (ctx.realm_id, GASTALDO, model, Jsonb(personality)),
    ).fetchone()[0]
    ctx.actors[GASTALDO] = Actor(actor_id, GASTALDO, model, personality.get("traits", {}), personality)


def _rounds_held(ctx: MeetingContext) -> int:
    """@brief Rounds that reached the Chancellor's summary. A round that broke
    before it (game 7: a crash after the Voice had spoken) does not count,
    so the meeting can be held again instead of leaving the turn stuck."""
    return ctx.conn.execute(
        "SELECT coalesce(max(round), 0) FROM council_messages WHERE realm_id = %s AND turn = %s"
        " AND kind = 'summary'",
        (ctx.realm_id, ctx.turn),
    ).fetchone()[0]


def _plan_approved(ctx: MeetingContext) -> bool:
    return ctx.conn.execute(
        "SELECT EXISTS (SELECT 1 FROM orders WHERE realm_id = %s AND turn = %s"
        " AND issued_by_actor_id IS NOT NULL)",
        (ctx.realm_id, ctx.turn),
    ).fetchone()[0]


def _check_meeting(ctx: MeetingContext) -> None:
    if _rounds_held(ctx) > 0:
        raise MeetingAlreadyHeldError(f"the council of turn {ctx.turn} already met")


def _check_directive(ctx: MeetingContext, settings: CouncilSettings) -> int:
    """@return The number of rounds already held."""
    rounds = _rounds_held(ctx)
    if rounds == 0:
        raise NoMeetingYetError("hold the meeting before giving a directive")
    if _plan_approved(ctx):
        raise AlreadyApprovedError("the plan of this turn is already approved")
    if rounds - 1 >= settings.max_directives_per_turn:
        raise TooManyDirectivesError(f"at most {settings.max_directives_per_turn} directives per turn")
    return rounds


def check_meeting_allowed(conn: psycopg.Connection, realm_id: int) -> None:
    """@brief Same checks as hold_meeting(), without any model call: lets the
    web UI refuse at once instead of failing later in the background.
    @throws NoOpenTurnError, MeetingAlreadyHeldError
    """
    _check_meeting(load_context(conn, realm_id, None, None))


def check_directive_allowed(conn: psycopg.Connection, realm_id: int, settings: CouncilSettings) -> None:
    """@brief Same checks as give_directive(), without any model call."""
    _check_directive(load_context(conn, realm_id, None, settings), settings)


def hold_meeting(conn: psycopg.Connection, realm_id: int, client, settings: CouncilSettings) -> int:
    """@brief First round of the open turn. @return the round number (1).
    @throws NoOpenTurnError, MeetingAlreadyHeldError
    Not one transaction on purpose: model calls take seconds each, and the
    messages already written stay useful if a later call fails.
    """
    ctx = load_context(conn, realm_id, client, settings)
    _check_meeting(ctx)
    ensure_gastaldo(ctx)
    if is_reflection_turn(ctx.turn):
        # 1 extra call per council member, before they speak, so the new
        # lessons are already in this meeting's briefings.
        for role in (*ministers_of(ctx), "chancellor"):
            if role in ctx.actors:
                _reflect(ctx, ctx.actors[role])
    # Imported here: the voice module builds on this one (no import cycle).
    from server.council import voice
    voice.speak_in_square(ctx)  # the people first, so the council hears them
    from server.council import people
    people.decide(ctx)  # then what they will do this month (and maybe a petition)
    _run_round(ctx, 1)
    return 1


def give_directive(conn: psycopg.Connection, realm_id: int, client,
                   settings: CouncilSettings, text: str) -> int:
    """@brief Store the sovereign's directive and run a new round.
    @return The new round number.
    @throws NoOpenTurnError, NoMeetingYetError, AlreadyApprovedError, TooManyDirectivesError
    """
    ctx = load_context(conn, realm_id, client, settings)
    new_round = _check_directive(ctx, settings) + 1
    insert_message(ctx, new_round, "directive", None, text, {})
    _run_round(ctx, new_round)
    return new_round


@dataclass
class CouncilState:
    turn: int
    rounds_held: int
    approved: bool
    directives_left: int


def council_state(conn: psycopg.Connection, realm_id: int, settings: CouncilSettings) -> CouncilState:
    """@brief Where the council of the open turn stands (for the web UI).
    @throws NoOpenTurnError
    """
    ctx = load_context(conn, realm_id, None, settings)
    rounds = _rounds_held(ctx)
    directives_used = max(0, rounds - 1)
    return CouncilState(
        ctx.turn, rounds, _plan_approved(ctx), max(0, settings.max_directives_per_turn - directives_used)
    )


def _granted_petition_action(conn: psycopg.Connection, realm_id: int, turn: int) -> str | None:
    """@brief The action ("set_tax", ...) of this turn's granted petition, if any."""
    row = conn.execute(
        "SELECT d.petition->>'action' FROM people_decisions d"
        " JOIN petition_answers a ON a.decision_id = d.id"
        " WHERE d.realm_id = %s AND d.turn = %s AND a.answer = 'granted'",
        (realm_id, turn),
    ).fetchone()
    return row[0] if row else None


def approve_plan(conn: psycopg.Connection, realm_id: int, excluded: list[int]) -> list[int]:
    """@brief Turn the latest plan into orders of the turn, each recorded with
    the minister who proposed it. Plan order becomes the order priority.
    @param excluded Plan positions (0-based) the sovereign removes.
    @return Ids of the stored orders.
    @throws NoOpenTurnError, NoMeetingYetError, AlreadyApprovedError, ValueError
    """
    with conn.transaction():
        ctx = load_context(conn, realm_id, None, None)
        if _plan_approved(ctx):
            raise AlreadyApprovedError("the plan of this turn is already approved")
        row = conn.execute(
            "SELECT payload FROM council_messages WHERE realm_id = %s AND turn = %s"
            " AND kind = 'summary' ORDER BY round DESC LIMIT 1",
            (realm_id, ctx.turn),
        ).fetchone()
        if row is None:
            raise NoMeetingYetError("there is no plan to approve yet")
        plan = row[0]["plan"]
        out_of_range = [index for index in excluded if not 0 <= index < len(plan)]
        if out_of_range:
            raise ValueError(f"plan has {len(plan)} orders, cannot exclude {out_of_range}")
        granted = _granted_petition_action(conn, realm_id, ctx.turn)
        order_ids = []
        for index, item in enumerate(plan):
            if index in excluded:
                continue
            if item["order"]["action"] == granted:
                continue  # a granted petition already decides this law (game 5)
            proposer = ctx.actors[item["proposer"]]
            order_ids.append(
                games.submit_order(conn, realm_id, item["order"], priority=index, actor_id=proposer.id)
            )
    return order_ids


def list_messages(conn: psycopg.Connection, realm_id: int, turn: int) -> list[dict]:
    """@brief Council messages of a turn for the realm's sovereign. Read as the
    server: the sovereign may see every level of their own realm anyway.
    """
    rows = conn.execute(
        "SELECT m.id, m.round, m.kind, a.role, m.content, m.payload, m.created_at"
        " FROM council_messages m LEFT JOIN actors a ON a.id = m.speaker_actor_id"
        " WHERE m.realm_id = %s AND m.turn = %s ORDER BY m.id",
        (realm_id, turn),
    ).fetchall()
    keys = ("id", "round", "kind", "speaker", "content", "payload", "created_at")
    return [dict(zip(keys, row)) for row in rows]
