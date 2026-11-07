"""@brief Model clients: OpenRouter for real play, a deterministic fake for
tests and free play. Both expose the same complete() call.

Hidden costs of OpenRouterClient: every call is a blocking HTTP request
(seconds, up to timeout_seconds); it holds the calling thread and, during
a meeting, one pooled DB connection.
"""

import json
import time
from dataclasses import dataclass

import httpx2

from server.council.settings import ModelPrice


@dataclass
class LLMReply:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class LLMError(Exception):
    """A call that produced no usable text. status goes to model_calls."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status  # "timeout" or "http_error"


def _estimated_cost(price: ModelPrice | None, input_tokens: int, output_tokens: int) -> float:
    if price is None:
        return 0.0
    return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


class OpenRouterClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: int, prices: dict[str, ModelPrice],
                 max_output_tokens: int):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is empty: set it in .env or use provider 'fake'")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout_seconds
        self._prices = prices
        self._max_output_tokens = max_output_tokens

    def _post(self, body: dict) -> tuple[int, bytes]:
        """@brief POST with a deadline on the WHOLE call, not on each read.

        httpx's timeout only bounds each single network wait, and OpenRouter
        keeps the connection alive while the model reasons, so a plain post
        once ran for 221 s with a 60 s timeout. Here the body is read in
        chunks and the call is abandoned once the deadline has passed.
        Limit: the deadline is checked when a chunk arrives; a silent server
        is still cut by the per-read timeout, so the worst case is about
        twice timeout_seconds.
        Hidden cost: OpenRouter may still bill the tokens generated before
        the abort, and we never learn that cost (the budget undercounts).
        @throws LLMError("timeout") past the deadline.
        """
        deadline = time.monotonic() + self._timeout
        chunks = []
        with httpx2.stream("POST", self._url, headers=self._headers, json=body,
                           timeout=self._timeout) as response:
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise LLMError("timeout", f"no complete answer within {self._timeout} s")
            return response.status_code, b"".join(chunks)

    def complete(self, role: str, model: str, system: str, user: str, schema: dict | None,
                 reasoning_effort: str | None = None) -> LLMReply:
        """@brief One chat completion.
        @param role Council role, only for the fake client and for logs.
        @param schema JSON schema of the expected object (sent as a hint;
               strict mode is off because not every provider supports it),
               or None for a plain text answer (private audiences).
        @param reasoning_effort "none", "low", ...; None = model default.
        @throws LLMError on timeout or HTTP error.
        """
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "usage": {"include": True},  # ask OpenRouter to return the cost
            # Reasoning included. Without a cap a model once looped up to
            # 131,072 tokens ($0.074, 31 % of a whole game). A reply cut here
            # is incomplete JSON, refused and retried like any invalid reply.
            "max_tokens": self._max_output_tokens,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": f"{role}_reply", "strict": False, "schema": schema},
            }
        if reasoning_effort is not None:
            body["reasoning"] = {"effort": reasoning_effort}
        started = time.monotonic()
        try:
            status_code, content = self._post(body)
        except httpx2.TimeoutException as error:
            raise LLMError("timeout", str(error)) from error
        except httpx2.HTTPError as error:
            raise LLMError("http_error", str(error)) from error
        latency_ms = int((time.monotonic() - started) * 1000)
        text_body = content.decode("utf-8", errors="replace")
        if status_code != 200:
            raise LLMError("http_error", f"HTTP {status_code}: {text_body[:300]}")
        try:
            data = json.loads(text_body)
        except json.JSONDecodeError as error:
            raise LLMError("http_error", f"not JSON from the provider: {text_body[:300]}") from error
        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = usage.get("cost")
        if cost is None:  # fall back to the prices in council.toml
            cost = _estimated_cost(self._prices.get(model), input_tokens, output_tokens)
        text = data["choices"][0]["message"].get("content") or ""
        return LLMReply(text, input_tokens, output_tokens, float(cost), latency_ms)


# Default answers of the fake council: plausible, always valid orders.
FAKE_MINISTER_REPLIES = {
    "treasurer": {
        # A feast, not "set_ration normal": a no-change order is dropped from plans.
        "report": "Maestà, le casse reggono. Propongo una piccola festa per il popolo.",
        "proposals": [{"action": "hold_feast", "gold": 10}],
    },
    "architect": {
        "report": "Maestà, una nuova fattoria ci proteggerebbe dal prossimo inverno.",
        "proposals": [{"action": "build", "building": "farm"}],
    },
}
PROPOSALS_MARKER = "Proposals (JSON): "


class FakeClient:
    """@brief Deterministic stand-in for the models: no network, no cost.
    @param script Optional role -> list of answers used in order before the
           defaults; an answer is a str (raw text) or an LLMError to raise.
    """

    def __init__(self, script: dict[str, list] | None = None):
        self._script = {role: list(answers) for role, answers in (script or {}).items()}
        self.calls: list[dict] = []  # every request, for test assertions

    def queue(self, role: str, *answers) -> None:
        """@brief Add scripted answers for a role, used before the defaults."""
        self._script.setdefault(role, []).extend(answers)

    def _default_text(self, role: str, user: str, schema: dict | None) -> str:
        if schema is None and role == "square_voice":
            return "In piazza si mormora che il pane basti, ma le madri guardano già all'inverno."
        if schema is None:  # private audience: plain text
            return f"Maestà, il vostro {role} vi ascolta e terrà conto delle vostre parole."
        if "decision" in schema.get("properties", {}):  # the chancellery reviews a mandate
            return json.dumps({"decision": "approved", "mandate": "Mandato di prova redatto dalla cancelleria.",
                               "reply": "Maestà, la cancelleria ha approvato e redatto il mandato."})
        if "stance" in schema.get("properties", {}):  # debate on the plan
            return json.dumps({"stance": "agree", "comment": f"Maestà, il {role} approva il piano."})
        if role == "people":
            return json.dumps({"effort_pct": 0, "birth_pct": 100, "petition": None,
                               "reason": "Test: nothing weighs on the people."})
        if "new_lessons" in schema.get("properties", {}):
            return json.dumps({"actions": [], "new_lessons": [f"Lezione di prova del {role} (turno 1)"]})
        if role != "chancellor":
            return json.dumps(FAKE_MINISTER_REPLIES[role])
        # The fake Chancellor approves every proposal it was shown.
        plan = []
        for line in user.splitlines():
            if line.startswith(PROPOSALS_MARKER):
                plan = json.loads(line[len(PROPOSALS_MARKER):])
        return json.dumps({"summary": "Maestà, ecco il piano del consiglio.", "plan": plan})

    def complete(self, role: str, model: str, system: str, user: str, schema: dict | None,
                 reasoning_effort: str | None = None) -> LLMReply:
        self.calls.append({"role": role, "model": model, "system": system, "user": user,
                           "reasoning_effort": reasoning_effort})
        scripted = self._script.get(role)
        answer = scripted.pop(0) if scripted else self._default_text(role, user, schema)
        if isinstance(answer, Exception):  # LLMError, or any crash a test wants
            raise answer
        tokens_in = (len(system) + len(user)) // 4  # rough, only for logs
        return LLMReply(answer, tokens_in, len(answer) // 4, 0.0, 0)
