from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class Match:
    match_id: str
    date: date
    format: str
    venue: Optional[str]
    team_home: str
    team_away: str
    winner: Optional[str]


@dataclass
class Player:
    player_id: str
    name: str


@dataclass
class Delivery:
    match_id: str
    innings: int
    over: int
    ball: int
    batter: str
    bowler: str
    non_striker: str
    runs_batter: int
    runs_extras: int
    runs_total: int
    wicket_kind: Optional[str]
    player_out: Optional[str]
