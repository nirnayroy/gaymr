"""DynamoQuotaStore round-trip + poller-integration fault test."""

from __future__ import annotations

import pytest

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")

from cricdata.ingest.cricdata_poller import FAIL_CLOSED_THRESHOLD, Poller, QuotaExceeded
from cricdata.ingest.dynamo_quota import DynamoQuotaStore


def _table(ddb):
    return ddb.create_table(
        TableName="q",
        KeySchema=[{"AttributeName": "date", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "date", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@moto.mock_aws
def test_increment_round_trips():
    ddb = boto3.resource("dynamodb", region_name="ap-south-1")
    _table(ddb).wait_until_exists()
    store = DynamoQuotaStore(ddb, "q")
    assert store.get("2026-05-15") == 0
    assert store.increment("2026-05-15") == 1
    assert store.increment("2026-05-15") == 2
    assert store.get("2026-05-15") == 2


@moto.mock_aws
def test_poller_fails_closed_against_dynamo():
    ddb = boto3.resource("dynamodb", region_name="ap-south-1")
    _table(ddb).wait_until_exists()
    store = DynamoQuotaStore(ddb, "q")
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    for _ in range(FAIL_CLOSED_THRESHOLD):
        store.increment(today)

    poller = Poller(api_key="x", store=store)
    with pytest.raises(QuotaExceeded):
        poller.call("matches")
