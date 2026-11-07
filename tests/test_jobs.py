"""Background job registry: one job per realm, errors kept per kind of work."""

import time

from server.council.jobs import CouncilJobs


def _wait_until_free(jobs, realm_id, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while jobs.is_running(realm_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not jobs.is_running(realm_id)


def _fail():
    raise RuntimeError("model unreachable")


def test_one_job_per_realm():
    jobs = CouncilJobs()
    assert jobs.reserve(1, "meeting")
    assert not jobs.reserve(1, "audience:treasurer")
    assert jobs.reserve(2, "meeting")  # another realm is independent
    assert jobs.running_kind(1) == "meeting"


def test_failure_is_shown_only_for_its_own_kind():
    jobs = CouncilJobs()
    assert jobs.reserve(1, "audience:architect")
    jobs.start(1, _fail)
    _wait_until_free(jobs, 1)
    assert "model unreachable" in jobs.last_error(1, "audience:architect")
    assert jobs.last_error(1, "meeting") == ""
    assert jobs.last_error(1, "audience:treasurer") == ""


def test_a_new_try_clears_the_old_failure():
    jobs = CouncilJobs()
    jobs.reserve(1, "meeting")
    jobs.start(1, _fail)
    _wait_until_free(jobs, 1)
    assert jobs.last_error(1, "meeting")
    jobs.reserve(1, "meeting")
    assert jobs.last_error(1, "meeting") == ""
