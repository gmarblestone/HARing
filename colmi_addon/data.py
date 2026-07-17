"""Read-side helpers that query the sync database for the charts page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from colmi_r02_client import db


@dataclass
class DailyStepPoint:
    day: str  # ISO date
    steps: int
    calories: int
    distance: int


@dataclass
class HeartRatePoint:
    timestamp: str  # ISO datetime
    reading: int


def get_daily_steps(db_path: Path, address: str, days: int) -> list[DailyStepPoint]:
    """Sum step / calorie / distance samples per day for the last `days`."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    with db.get_db_session(db_path) as session:
        day = func.date(db.SportDetail.timestamp)
        stmt = (
            select(
                day.label("day"),
                func.sum(db.SportDetail.steps).label("steps"),
                func.sum(db.SportDetail.calories).label("calories"),
                func.sum(db.SportDetail.distance).label("distance"),
            )
            .join(db.Ring, db.Ring.ring_id == db.SportDetail.ring_id)
            .where(db.Ring.address == address)
            .where(db.SportDetail.timestamp >= since)
            .group_by(day)
            .order_by(day)
        )
        rows = session.execute(stmt).all()
    return [
        DailyStepPoint(
            day=str(r.day),
            steps=int(r.steps or 0),
            calories=int(r.calories or 0),
            distance=int(r.distance or 0),
        )
        for r in rows
    ]


def get_heart_rate_series(db_path: Path, address: str, days: int, limit: int = 2000) -> list[HeartRatePoint]:
    """Individual heart-rate samples for the last `days`, capped at `limit` most-recent rows."""
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
    with db.get_db_session(db_path) as session:
        stmt = (
            select(db.HeartRate.timestamp, db.HeartRate.reading)
            .join(db.Ring, db.Ring.ring_id == db.HeartRate.ring_id)
            .where(db.Ring.address == address)
            .where(db.HeartRate.timestamp >= since)
            .order_by(db.HeartRate.timestamp.desc())
            .limit(limit)
        )
        rows = session.execute(stmt).all()
    # Return oldest-first for nicer charts.
    return [HeartRatePoint(timestamp=r.timestamp.isoformat(), reading=int(r.reading)) for r in reversed(rows)]
