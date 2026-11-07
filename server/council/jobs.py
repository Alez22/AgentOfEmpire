"""@brief Council rounds running in the background, at most one per realm.

A round takes 30-150 s with real models: on a phone the HTTP request may
drop (screen off, network change), so the web UI starts the round here and
polls the stored messages instead of waiting for one long response.

Constraints:
- The registry lives in this process. That is correct only while the server
  runs ONE worker process (today: one uvicorn process). With several workers
  this must become a database lock (e.g. pg_try_advisory_lock per realm).
- Each running round holds one thread and one pooled DB connection.
- A server restart (also uvicorn --reload on a code change) kills running
  rounds: the messages already written stay, the round is just incomplete.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class JobStatus:
    kind: str  # "meeting", "directive" or "audience:<role>"
    started_at: float  # time.monotonic()
    error: str = ""  # last failure message, "" if none


class CouncilJobs:
    def __init__(self):
        self._lock = threading.Lock()
        self._running: dict[int, JobStatus] = {}
        # Keyed by (realm, kind): a failed audience must not show up on the
        # council panel, nor an audience with another member.
        self._last_error: dict[tuple[int, str], str] = {}

    def is_running(self, realm_id: int) -> bool:
        with self._lock:
            return realm_id in self._running

    def running_kind(self, realm_id: int) -> str | None:
        """@brief What is running for the realm, so each panel only reacts to its own work."""
        with self._lock:
            status = self._running.get(realm_id)
            return status.kind if status else None

    def last_error(self, realm_id: int, kind: str) -> str:
        """@brief Last failure of that kind of work for the realm ("" if none)."""
        with self._lock:
            return self._last_error.get((realm_id, kind), "")

    def reserve(self, realm_id: int, kind: str) -> bool:
        """@brief Claim the realm before checking or starting a round.
        @return False if a round is already running for this realm.
        """
        with self._lock:
            if realm_id in self._running:
                return False
            self._running[realm_id] = JobStatus(kind, time.monotonic())
            self._last_error.pop((realm_id, kind), None)  # a new try clears the old failure
            return True

    def release(self, realm_id: int, error: str = "") -> None:
        with self._lock:
            status = self._running.pop(realm_id, None)
            if error and status is not None:
                self._last_error[(realm_id, status.kind)] = error

    def start(self, realm_id: int, work: Callable[[], None]) -> None:
        """@brief Run work() in a daemon thread on an already reserved realm;
        the reservation is released when it ends, also on failure."""

        def run() -> None:
            try:
                work()
            except Exception as error:  # noqa: BLE001 - reported to the player, not swallowed
                self.release(realm_id, f"{type(error).__name__}: {error}")
                return
            self.release(realm_id)

        threading.Thread(target=run, name=f"council-realm-{realm_id}", daemon=True).start()
