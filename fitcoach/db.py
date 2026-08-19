"""Хранилище на SQLite: тренировки, сон, замеры, план, дайджесты."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS workouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    date          TEXT    NOT NULL,          -- YYYY-MM-DD
    kind          TEXT    NOT NULL,          -- strength | cardio | mobility | other
    title         TEXT,
    duration_min  REAL,
    rpe           REAL,
    avg_hr        REAL,
    max_hr        REAL,
    distance_km   REAL,
    tonnage_kg    REAL,
    exercises     TEXT    NOT NULL DEFAULT '[]',   -- JSON
    notes         TEXT,
    source        TEXT    NOT NULL DEFAULT 'text', -- text | photo | file
    raw           TEXT,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workouts_user_date ON workouts(user_id, date);

CREATE TABLE IF NOT EXISTS sleep (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    date            TEXT    NOT NULL,        -- дата пробуждения
    total_min       REAL,
    deep_min        REAL,
    rem_min         REAL,
    light_min       REAL,
    awake_min       REAL,
    score           REAL,
    resting_hr      REAL,
    hrv_ms          REAL,
    body_battery    REAL,
    stress_avg      REAL,
    spo2            REAL,
    source          TEXT    NOT NULL DEFAULT 'text',
    raw             TEXT,
    created_at      TEXT    NOT NULL,
    UNIQUE(user_id, date) ON CONFLICT REPLACE
);

CREATE TABLE IF NOT EXISTS metrics (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    date       TEXT    NOT NULL,
    name       TEXT    NOT NULL,             -- weight_kg | waist_cm | kcal | protein_g ...
    value      REAL    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_user_date ON metrics(user_id, date);

CREATE TABLE IF NOT EXISTS profile (
    user_id    INTEGER PRIMARY KEY,
    chat_id    INTEGER,
    data       TEXT NOT NULL DEFAULT '{}',   -- JSON: цели, антропометрия, ограничения
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan (
    user_id     INTEGER PRIMARY KEY,
    week_start  TEXT NOT NULL,               -- понедельник недели
    data        TEXT NOT NULL,               -- JSON: дни, сессии, упражнения
    rationale   TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT    NOT NULL,             -- morning | weekly | analysis | chat
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, created_at);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------- workouts

    def add_workout(self, user_id: int, workout: dict[str, Any], *, source: str = "text",
                    raw: str | None = None) -> int:
        exercises = workout.get("exercises") or []
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO workouts (user_id, date, kind, title, duration_min, rpe,
                       avg_hr, max_hr, distance_km, tonnage_kg, exercises, notes,
                       source, raw, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    workout.get("date") or date.today().isoformat(),
                    workout.get("kind") or "other",
                    workout.get("title"),
                    workout.get("duration_min"),
                    workout.get("rpe"),
                    workout.get("avg_hr"),
                    workout.get("max_hr"),
                    workout.get("distance_km"),
                    workout.get("tonnage_kg") or tonnage(exercises),
                    json.dumps(exercises, ensure_ascii=False),
                    workout.get("notes"),
                    source,
                    raw,
                    _now(),
                ),
            )
            return int(cur.lastrowid)

    def recent_workouts(self, user_id: int, days: int = 28) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM workouts
                   WHERE user_id = ? AND date >= date('now', ?)
                   ORDER BY date DESC, id DESC""",
                (user_id, f"-{days} days"),
            ).fetchall()
        return [_workout_row(r) for r in rows]

    # ------------------------------------------------------------------- sleep

    def add_sleep(self, user_id: int, sleep: dict[str, Any], *, source: str = "text",
                  raw: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO sleep (user_id, date, total_min, deep_min, rem_min, light_min,
                       awake_min, score, resting_hr, hrv_ms, body_battery, stress_avg, spo2,
                       source, raw, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    sleep.get("date") or date.today().isoformat(),
                    sleep.get("total_min"),
                    sleep.get("deep_min"),
                    sleep.get("rem_min"),
                    sleep.get("light_min"),
                    sleep.get("awake_min"),
                    sleep.get("score"),
                    sleep.get("resting_hr"),
                    sleep.get("hrv_ms"),
                    sleep.get("body_battery"),
                    sleep.get("stress_avg"),
                    sleep.get("spo2"),
                    source,
                    raw,
                    _now(),
                ),
            )

    def recent_sleep(self, user_id: int, days: int = 14) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM sleep
                   WHERE user_id = ? AND date >= date('now', ?)
                   ORDER BY date DESC""",
                (user_id, f"-{days} days"),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- metrics

    def add_metric(self, user_id: int, name: str, value: float,
                   when: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO metrics (user_id, date, name, value, created_at) VALUES (?,?,?,?,?)",
                (user_id, when or date.today().isoformat(), name, float(value), _now()),
            )

    def recent_metrics(self, user_id: int, days: int = 30) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM metrics
                   WHERE user_id = ? AND date >= date('now', ?)
                   ORDER BY date DESC""",
                (user_id, f"-{days} days"),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- profile

    def get_profile(self, user_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT data FROM profile WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row["data"]) if row else {}

    def update_profile(self, user_id: int, patch: dict[str, Any],
                       chat_id: int | None = None) -> dict[str, Any]:
        data = self.get_profile(user_id)
        data.update({k: v for k, v in patch.items() if v is not None})
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO profile (user_id, chat_id, data, updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                       data = excluded.data,
                       chat_id = COALESCE(excluded.chat_id, profile.chat_id),
                       updated_at = excluded.updated_at""",
                (user_id, chat_id, json.dumps(data, ensure_ascii=False), _now()),
            )
        return data

    def subscribers(self) -> list[tuple[int, int]]:
        """(user_id, chat_id) всех, кому можно слать дайджест."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT user_id, chat_id FROM profile WHERE chat_id IS NOT NULL"
            ).fetchall()
        return [(r["user_id"], r["chat_id"]) for r in rows]

    # -------------------------------------------------------------------- plan

    def get_plan(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM plan WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return {
            "week_start": row["week_start"],
            "rationale": row["rationale"],
            "updated_at": row["updated_at"],
            **json.loads(row["data"]),
        }

    def save_plan(self, user_id: int, week_start: str, plan: dict[str, Any],
                  rationale: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO plan (user_id, week_start, data, rationale, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                       week_start = excluded.week_start,
                       data = excluded.data,
                       rationale = excluded.rationale,
                       updated_at = excluded.updated_at""",
                (user_id, week_start, json.dumps(plan, ensure_ascii=False), rationale, _now()),
            )

    # ---------------------------------------------------------------- messages

    def log_message(self, user_id: int, kind: str, body: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO messages (user_id, kind, body, created_at) VALUES (?,?,?,?)",
                (user_id, kind, body, _now()),
            )

    def last_message(self, user_id: int, kind: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE user_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
                (user_id, kind),
            ).fetchone()
        return dict(row) if row else None


def tonnage(exercises: list[dict[str, Any]]) -> float:
    """Суммарный тоннаж: сумма вес × повторы по всем подходам."""
    total = 0.0
    for ex in exercises:
        for st in ex.get("sets") or []:
            weight = st.get("weight_kg")
            reps = st.get("reps")
            if weight and reps:
                total += float(weight) * float(reps)
    return round(total, 1)


def _workout_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["exercises"] = json.loads(data.get("exercises") or "[]")
    return data


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
