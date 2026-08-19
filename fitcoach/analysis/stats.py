"""Детерминированные агрегаты. Считаем цифры кодом, а не моделью."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Any

from ..db import Database


def week_start(day: date | None = None) -> date:
    day = day or date.today()
    return day - timedelta(days=day.weekday())


def weekly_summary(workouts: list[dict[str, Any]], weeks: int = 4) -> list[dict[str, Any]]:
    """Свод по неделям: число сессий, тоннаж, километраж, средний RPE."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for workout in workouts:
        try:
            day = date.fromisoformat(workout["date"])
        except (ValueError, TypeError, KeyError):
            continue
        buckets[week_start(day).isoformat()].append(workout)

    summaries = []
    for start in sorted(buckets, reverse=True)[:weeks]:
        items = buckets[start]
        rpes = [w["rpe"] for w in items if w.get("rpe")]
        summaries.append(
            {
                "week_start": start,
                "sessions": len(items),
                "strength_sessions": sum(1 for w in items if w.get("kind") == "strength"),
                "cardio_sessions": sum(1 for w in items if w.get("kind") == "cardio"),
                "tonnage_kg": round(sum(w.get("tonnage_kg") or 0 for w in items), 1),
                "distance_km": round(sum(w.get("distance_km") or 0 for w in items), 2),
                "duration_min": round(sum(w.get("duration_min") or 0 for w in items), 1),
                "avg_rpe": round(mean(rpes), 2) if rpes else None,
            }
        )
    return summaries


def sleep_trend(nights: list[dict[str, Any]]) -> dict[str, Any]:
    """Последняя ночь и её отклонение от средних за 7 дней."""
    if not nights:
        return {"last": None, "avg_7d": {}, "delta": {}}

    fields = ("total_min", "score", "hrv_ms", "resting_hr", "deep_min", "body_battery")
    last = nights[0]
    window = nights[:7]

    avg = {}
    for field in fields:
        values = [n[field] for n in window if n.get(field) is not None]
        if values:
            avg[field] = round(mean(values), 1)

    delta = {
        field: round(last[field] - avg[field], 1)
        for field in fields
        if last.get(field) is not None and field in avg
    }
    return {"last": last, "avg_7d": avg, "delta": delta, "nights_with_data": len(window)}


def metric_trend(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """По каждому показателю: последнее значение и изменение за период."""
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        by_name[metric["name"]].append(metric)

    trends = {}
    for name, items in by_name.items():
        items.sort(key=lambda m: m["date"])
        first, last = items[0], items[-1]
        trends[name] = {
            "last": last["value"],
            "last_date": last["date"],
            "change": round(last["value"] - first["value"], 2),
            "points": len(items),
        }
    return trends


def build_context(db: Database, user_id: int, *, days: int = 28) -> dict[str, Any]:
    """Единый контекст, который уходит в модель во всех сценариях."""
    workouts = db.recent_workouts(user_id, days=days)
    nights = db.recent_sleep(user_id, days=14)
    metrics = db.recent_metrics(user_id, days=days)

    return {
        "today": date.today().isoformat(),
        "weekday": date.today().strftime("%a").lower(),
        "profile": db.get_profile(user_id),
        "plan": db.get_plan(user_id),
        "weekly_summary": weekly_summary(workouts),
        "sleep": sleep_trend(nights),
        "metrics": metric_trend(metrics),
        "recent_workouts": [_slim(w) for w in workouts[:12]],
    }


def render_context(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, indent=2)


def _slim(workout: dict[str, Any]) -> dict[str, Any]:
    """Убираем из тренировки поля, бесполезные модели (raw, служебные id)."""
    keep = ("date", "kind", "title", "duration_min", "rpe", "avg_hr", "max_hr",
            "distance_km", "tonnage_kg", "exercises", "notes")
    return {k: workout.get(k) for k in keep if workout.get(k) not in (None, [], "")}
