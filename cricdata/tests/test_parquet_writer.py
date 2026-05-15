"""ParquetStore writes partitioned files with the expected layout."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pyarrow.parquet as pq
import pytest

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")

from cricdata.ingest.parquet_writer import ParquetStore
from cricdata.schema.models import Delivery, Match


@moto.mock_aws
def test_writes_partitioned_parquet():
    s3 = boto3.client("s3", region_name="ap-south-1")
    s3.create_bucket(
        Bucket="test-curated-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-south-1"},
    )
    store = ParquetStore(s3, "test-curated-bucket", prefix="curated")

    match = Match(
        match_id="m1", date=date(2024, 3, 22), format="T20",
        venue="Chepauk", team_home="CSK", team_away="RCB", winner="CSK",
    )
    deliveries = [
        Delivery("m1", 1, 0, 1, "F du Plessis", "D Chahar", "V Kohli",
                 1, 0, 1, None, None),
        Delivery("m1", 1, 0, 2, "V Kohli", "D Chahar", "F du Plessis",
                 4, 0, 4, None, None),
    ]
    store.write(match, deliveries)
    store.close()

    keys = sorted(o["Key"] for o in s3.list_objects_v2(Bucket="test-curated-bucket")["Contents"])
    assert any("matches/year=2024/format=T20/" in k for k in keys)
    assert any("deliveries/year=2024/format=T20/" in k for k in keys)

    delivery_key = next(k for k in keys if "deliveries/" in k)
    body = s3.get_object(Bucket="test-curated-bucket", Key=delivery_key)["Body"].read()
    table = pq.read_table(BytesIO(body))
    assert table.num_rows == 2
    assert set(table.column_names) >= {"match_id", "batter", "runs_batter"}
