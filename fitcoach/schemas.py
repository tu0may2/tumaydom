"""JSON-схемы для структурированных ответов модели.

Structured outputs требуют `additionalProperties: false` и перечисления всех
полей в `required`, поэтому «необязательные» поля описаны как nullable.
"""

from __future__ import annotations

from typing import Any


def _nullable(*types: str) -> dict[str, Any]:
    return {"type": [*types, "null"]}


NUM = _nullable("number")
STR = _nullable("string")

SET_SCHEMA = {
    "type": "object",
    "properties": {
        "weight_kg": NUM,
        "reps": _nullable("integer"),
        "rpe": NUM,
        "duration_sec": NUM,
    },
    "required": ["weight_kg", "reps", "rpe", "duration_sec"],
    "additionalProperties": False,
}

EXERCISE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "sets": {"type": "array", "items": SET_SCHEMA},
        "notes": STR,
    },
    "required": ["name", "sets", "notes"],
    "additionalProperties": False,
}

WORKOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "date": STR,
        "kind": {"type": "string", "enum": ["strength", "cardio", "mobility", "other"]},
        "title": STR,
        "duration_min": NUM,
        "rpe": NUM,
        "avg_hr": NUM,
        "max_hr": NUM,
        "distance_km": NUM,
        "exercises": {"type": "array", "items": EXERCISE_SCHEMA},
        "notes": STR,
    },
    "required": ["date", "kind", "title", "duration_min", "rpe", "avg_hr", "max_hr",
                 "distance_km", "exercises", "notes"],
    "additionalProperties": False,
}

SLEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "date": STR,
        "total_min": NUM,
        "deep_min": NUM,
        "rem_min": NUM,
        "light_min": NUM,
        "awake_min": NUM,
        "score": NUM,
        "resting_hr": NUM,
        "hrv_ms": NUM,
        "body_battery": NUM,
        "stress_avg": NUM,
        "spo2": NUM,
    },
    "required": ["date", "total_min", "deep_min", "rem_min", "light_min", "awake_min",
                 "score", "resting_hr", "hrv_ms", "body_battery", "stress_avg", "spo2"],
    "additionalProperties": False,
}

METRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "date": STR,
        "name": {"type": "string"},
        "value": {"type": "number"},
    },
    "required": ["date", "name", "value"],
    "additionalProperties": False,
}

# Единый разбор входящего сообщения: что это вообще было.
INGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["workout", "sleep", "metrics", "question", "profile", "unknown"],
        },
        "confidence": {"type": "number"},
        "workouts": {"type": "array", "items": WORKOUT_SCHEMA},
        "sleep": {"type": "array", "items": SLEEP_SCHEMA},
        "metrics": {"type": "array", "items": METRIC_SCHEMA},
        "profile_patch": {
            "type": "object",
            "properties": {
                "goal": STR,
                "experience": STR,
                "height_cm": NUM,
                "weight_kg": NUM,
                "age": _nullable("integer"),
                "sex": STR,
                "days_per_week": _nullable("integer"),
                "equipment": STR,
                "limitations": STR,
                "diet_notes": STR,
            },
            "required": ["goal", "experience", "height_cm", "weight_kg", "age", "sex",
                         "days_per_week", "equipment", "limitations", "diet_notes"],
            "additionalProperties": False,
        },
        "comment": {"type": "string"},
    },
    "required": ["intent", "confidence", "workouts", "sleep", "metrics", "profile_patch",
                 "comment"],
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "week_start": {"type": "string"},
        "focus": {"type": "string"},
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "weekday": {
                        "type": "string",
                        "enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["strength", "cardio", "mobility", "rest", "other"],
                    },
                    "title": {"type": "string"},
                    "blocks": {"type": "array", "items": {"type": "string"}},
                    "target_rpe": NUM,
                },
                "required": ["weekday", "kind", "title", "blocks", "target_rpe"],
                "additionalProperties": False,
            },
        },
        "nutrition": {
            "type": "object",
            "properties": {
                "kcal": NUM,
                "protein_g": NUM,
                "fat_g": NUM,
                "carbs_g": NUM,
                "notes": {"type": "string"},
            },
            "required": ["kcal", "protein_g", "fat_g", "carbs_g", "notes"],
            "additionalProperties": False,
        },
        "rationale": {"type": "string"},
    },
    "required": ["week_start", "focus", "days", "nutrition", "rationale"],
    "additionalProperties": False,
}
