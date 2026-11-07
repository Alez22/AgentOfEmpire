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
    def __init__(self, base_url: str, api_key: str, timeout_seconds: int, prices: dict[str, ModelPrice]):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is empty: set it in .env or use provider 'fake'")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout_seconds
        self._prices = prices

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
            response = httpx2.post(self._url, headers=self._headers, json=body, timeout=self._timeout)
        except httpx2.TimeoutException as error:
            raise LLMError("timeout", str(error)) from error
        except httpx2.HTTPError as error:
            raise LLMError("http_error", str(error)) from error
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code != 200:
            raise LLMError("http_error", f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
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
        "report": "Maestà, le casse reggono. Propongo di mantenere razioni normali.",
        "proposals": [{"action": "set_ration", "ration": "normal"}],
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
        if isinstance(answer, LLMError):
            raise answer
        tokens_in = (len(system) + len(user)) // 4  # rough, only for logs
        return LLMReply(answer, tokens_in, len(answer) // 4, 0.0, 0)
