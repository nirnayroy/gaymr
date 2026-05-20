"""EventBridge-trigger Lambda: poll CricketData.org once per schedule fire.

The schedule is created **disabled** by CDK. Phase 3 turns it on only after
(1) the fail-closed quota guard is verified end-to-end via fault injection
and (2) CloudWatch alarms are confirmed wired to SNS.

Env:
    CRICDATA_API_KEY_PARAM   SSM parameter name holding the API key
    QUOTA_TABLE              DynamoDB table for the api_quota counter
    RAW_BUCKET               S3 bucket for raw poller output
    RAW_PREFIX               key prefix (default "raw/cricdata")
    METRIC_NAMESPACE         CloudWatch namespace (default "cricdata")
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import boto3

from cricdata.ingest.cricdata_poller import Poller, QuotaExceeded
from cricdata.ingest.dynamo_quota import DynamoQuotaStore

SSM = boto3.client("ssm")
DDB = boto3.resource("dynamodb")
S3 = boto3.client("s3")
CW = boto3.client("cloudwatch")

_API_KEY: str | None = None


def _api_key() -> str:
    global _API_KEY
    if _API_KEY is None:
        param = os.environ["CRICDATA_API_KEY_PARAM"]
        _API_KEY = SSM.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    return _API_KEY


def _emit(metric: str, value: float, unit: str = "Count") -> None:
    namespace = os.environ.get("METRIC_NAMESPACE", "cricdata")
    try:
        CW.put_metric_data(
            Namespace=namespace,
            MetricData=[{"MetricName": metric, "Value": value, "Unit": unit}],
        )
    except Exception:
        # Telemetry must never break the poller. The DDB-backed counter is
        # the source of truth for the quota; the metric is for alarming only.
        pass


def handler(_event: dict, _context) -> dict:
    quota = DynamoQuotaStore(DDB, os.environ["QUOTA_TABLE"])
    poller = Poller(api_key=_api_key(), store=quota)
    today = datetime.now(timezone.utc).date().isoformat()

    try:
        payload = poller.call("currentMatches", {"offset": 0})
    except QuotaExceeded as e:
        _emit("QuotaExceeded", 1)
        _emit("QuotaHits", quota.get(today))
        return {"status": "skipped", "reason": str(e)}

    _emit("QuotaHits", quota.get(today))

    bucket = os.environ["RAW_BUCKET"]
    prefix = os.environ.get("RAW_PREFIX", "raw/cricdata")
    now = datetime.now(timezone.utc)
    key = f"{prefix}/{now.strftime('%Y/%m/%d')}/currentMatches-{int(time.time())}.json"
    S3.put_object(Bucket=bucket, Key=key, Body=json.dumps(payload).encode())

    return {"status": "ok", "s3_key": key}
