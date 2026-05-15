"""S3-trigger Lambda: Cricsheet ZIP in raw/ -> partitioned Parquet in curated/.

Env:
    CURATED_BUCKET   target bucket for Parquet output
    CURATED_PREFIX   key prefix under curated (default "curated")
"""

from __future__ import annotations

import os
from urllib.parse import unquote_plus

import boto3

from cricdata.ingest.cricsheet import iter_matches
from cricdata.ingest.parquet_writer import ParquetStore

S3 = boto3.client("s3")


def handler(event: dict, _context) -> dict:
    curated_bucket = os.environ["CURATED_BUCKET"]
    curated_prefix = os.environ.get("CURATED_PREFIX", "curated")

    n_matches = n_deliveries = 0
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        obj = S3.get_object(Bucket=bucket, Key=key)
        zip_bytes = obj["Body"].read()

        store = ParquetStore(S3, curated_bucket, curated_prefix)
        try:
            for match, deliveries in iter_matches(zip_bytes):
                store.write(match, deliveries)
                n_matches += 1
                n_deliveries += len(deliveries)
        finally:
            store.close()

    return {"matches": n_matches, "deliveries": n_deliveries}
