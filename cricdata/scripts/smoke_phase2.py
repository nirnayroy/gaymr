"""Phase 2 smoke: upload one Cricsheet match ZIP to raw/ and verify Parquet lands.

Usage:
    python -m cricdata.scripts.smoke_phase2 <raw_bucket> <curated_bucket> [zip_path]
"""

from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

import boto3

from cricdata.ingest.cricsheet import fetch_zip

DEFAULT_URL = "https://cricsheet.org/downloads/ipl_json.zip"
DEFAULT_ZIP = Path(__file__).resolve().parents[1] / ".cache" / "ipl_json.zip"


def _one_match_zip(src: Path) -> bytes:
    with zipfile.ZipFile(src) as zin:
        first = next(n for n in zin.namelist() if n.endswith(".json"))
        data = zin.read(first)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr(first, data)
    return out.getvalue()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    raw_bucket, curated_bucket = sys.argv[1], sys.argv[2]
    src = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_ZIP
    if not src.exists():
        fetch_zip(DEFAULT_URL, src)

    s3 = boto3.client("s3")
    key = f"raw/cricsheet/smoke-{int(time.time())}.zip"
    s3.put_object(Bucket=raw_bucket, Key=key, Body=_one_match_zip(src))
    print(f"uploaded s3://{raw_bucket}/{key}")

    print("waiting up to 60s for Parquet to land...")
    for _ in range(20):
        time.sleep(3)
        resp = s3.list_objects_v2(Bucket=curated_bucket, Prefix="curated/deliveries/")
        if resp.get("KeyCount", 0) > 0:
            print(f"OK — {resp['KeyCount']} delivery file(s) in curated/")
            return 0
    print("FAIL: no Parquet appeared in 60s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
