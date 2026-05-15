"""Cricsheet ZIP downloader + per-match JSON parser.

Cricsheet ships match data as a ZIP of per-match JSON files. This module
downloads a ZIP (or reads a local one), iterates matches, and yields
typed records ready for the SQLite loader.
"""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Union

from cricdata.schema.models import Delivery, Match


def fetch_zip(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        urllib.request.urlretrieve(url, dest)
    return dest


def iter_matches(zip_source: Union[Path, bytes]) -> Iterator[tuple[Match, list[Delivery]]]:
    raw = zip_source.read_bytes() if isinstance(zip_source, Path) else zip_source
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            with zf.open(name) as f:
                doc = json.load(f)
            yield _parse_match(name, doc)


def _parse_match(filename: str, doc: dict) -> tuple[Match, list[Delivery]]:
    info = doc["info"]
    match_id = Path(filename).stem
    teams = info["teams"]
    match = Match(
        match_id=match_id,
        date=date.fromisoformat(info["dates"][0]),
        format=info.get("match_type", "unknown"),
        venue=info.get("venue"),
        team_home=teams[0],
        team_away=teams[1],
        winner=info.get("outcome", {}).get("winner"),
    )

    deliveries: list[Delivery] = []
    for innings_idx, innings in enumerate(doc.get("innings", []), start=1):
        for over in innings.get("overs", []):
            over_num = over["over"]
            for ball_idx, delivery in enumerate(over["deliveries"], start=1):
                runs = delivery["runs"]
                wickets = delivery.get("wickets") or []
                wicket = wickets[0] if wickets else {}
                deliveries.append(
                    Delivery(
                        match_id=match_id,
                        innings=innings_idx,
                        over=over_num,
                        ball=ball_idx,
                        batter=delivery["batter"],
                        bowler=delivery["bowler"],
                        non_striker=delivery["non_striker"],
                        runs_batter=runs["batter"],
                        runs_extras=runs["extras"],
                        runs_total=runs["total"],
                        wicket_kind=wicket.get("kind"),
                        player_out=wicket.get("player_out"),
                    )
                )
    return match, deliveries
