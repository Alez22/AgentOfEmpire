"""OpenRouterClient against a local HTTP server: no network, no cost.

The server sends its answer one byte every 0.2 s, like OpenRouter keeping
the connection alive while a model reasons. httpx's own timeout never fires
in that case; the client's deadline on the whole call must.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.council.llm import LLMError, OpenRouterClient

ANSWER = json.dumps({
    "choices": [{"message": {"content": "ok"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001},
}).encode()


class _Handler(BaseHTTPRequestHandler):
    byte_delay = 0.0  # seconds between bytes of the body
    bodies: list = []

    def do_POST(self):  # noqa: N802 (http.server naming)
        length = int(self.headers["Content-Length"])
        type(self).bodies.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(ANSWER)))
        self.end_headers()
        for byte in ANSWER:
            self.wfile.write(bytes([byte]))
            self.wfile.flush()
            time.sleep(self.byte_delay)

    def log_message(self, *args):  # keep the test output clean
        pass


@pytest.fixture
def server():
    _Handler.bodies = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def _client(httpd, timeout_seconds=1):
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    return OpenRouterClient(url, "test-key", timeout_seconds, prices={}, max_output_tokens=8000)


def test_answer_is_read_and_the_output_cap_is_sent(server):
    _Handler.byte_delay = 0.0
    reply = _client(server).complete("treasurer", "some/model", "system", "user", schema=None)
    assert reply.text == "ok" and reply.cost_usd == 0.0001
    assert _Handler.bodies[0]["max_tokens"] == 8000


def test_slow_trickle_hits_the_deadline_on_the_whole_call(server):
    _Handler.byte_delay = 0.2  # the full answer would take about 25 s
    started = time.monotonic()
    with pytest.raises(LLMError) as error:
        _client(server, timeout_seconds=1).complete("architect", "some/model", "s", "u", schema=None)
    assert error.value.status == "timeout"
    assert time.monotonic() - started < 3


def test_listed_models_get_no_schema_and_no_reasoning(server):
    _Handler.byte_delay = 0.0
    url = f"http://127.0.0.1:{server.server_address[1]}"
    client = OpenRouterClient(url, "test-key", 1, prices={}, max_output_tokens=8000,
                              models_without_json_schema=("plain/model",),
                              models_without_reasoning=("plain/model",))
    client.complete("treasurer", "plain/model", "s", "u", schema={"type": "object"}, reasoning_effort="low")
    client.complete("treasurer", "other/model", "s", "u", schema={"type": "object"}, reasoning_effort="low")
    plain, other = _Handler.bodies
    assert "response_format" not in plain and "reasoning" not in plain
    assert "response_format" in other and other["reasoning"] == {"effort": "low"}
    assert plain["provider"] == {"require_parameters": True}
