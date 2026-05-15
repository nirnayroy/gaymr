"""The fail-closed quota guard is non-negotiable. This test enforces it."""

import pytest

from cricdata.ingest.cricdata_poller import FAIL_CLOSED_THRESHOLD, Poller, QuotaExceeded


class StubStore:
    def __init__(self, hits: int):
        self.hits = hits
        self.calls = 0

    def get(self, day):
        return self.hits

    def increment(self, day):
        self.calls += 1
        self.hits += 1
        return self.hits


def test_refuses_at_threshold():
    poller = Poller(api_key="x", store=StubStore(FAIL_CLOSED_THRESHOLD))
    with pytest.raises(QuotaExceeded):
        poller.call("matches")


def test_refuses_above_threshold():
    poller = Poller(api_key="x", store=StubStore(FAIL_CLOSED_THRESHOLD + 10))
    with pytest.raises(QuotaExceeded):
        poller.call("matches")


def test_threshold_is_95():
    assert FAIL_CLOSED_THRESHOLD == 95
