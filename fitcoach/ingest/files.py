"""Импорт выгрузок: Garmin Connect CSV/JSON и произвольные таблицы.

Сначала пробуем детерминированный разбор известных колонок Garmin, чтобы не
платить за LLM на каждой строке. Если формат не распознан — возвращаем
подготовленный текстовый фрагмент, который скармливается парсеру на LLM.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any

MAX_LLM_CHARS = 12000

# Наиболее частые заголовки выгрузки активностей Garmin Connect (RU и EN).
_ACTIVITY_COLUMNS = {
    "date": ("date", "дата", "activity date", "start time", "время начала"),
    "title": ("title", "название", "activity name"),
    "kind": ("activity type", "тип активности", "type"),
    "duration": ("time", "duration", "время", "продолжительность"),
    "distance": ("distance", "дистанция"),
    "avg_hr": ("avg hr", "average hr", "средний пульс", "ср. пульс"),
    "max_hr": ("max hr", "максимальный пульс", "макс. пульс"),
}

_CARDIO_HINTS = ("run", "bike", "cycl", "swim", "row", "walk", "cardio", "elliptical",
                 "бег", "вело", "плав", "греб", "ходьб", "кардио")
_STRENGTH_HINTS = ("strength", "weight", "gym", "силов", "трениров с отягощ")


def load_file(name: str, blob: bytes) -> dict[str, Any]:
    """Разобрать файл выгрузки.

    Возвращает `{"workouts": [...], "sleep": [...], "text": str | None}`.
    Непустой `text` означает, что структуру не распознали и её нужно отдать LLM.
    """
    lower = name.lower()
    try:
        content = blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = blob.decode("latin-1")

    if lower.endswith((".csv", ".tsv")):
        workouts = _parse_activity_csv(content)
        if workouts:
            return {"workouts": workouts, "sleep": [], "text": None}
        return {"workouts": [], "sleep": [], "text": _truncate(content)}

    if lower.endswith(".json"):
        data = json.loads(content)
        sleep = _parse_sleep_json(data)
        if sleep:
            return {"workouts": [], "sleep": sleep, "text": None}
        return {"workouts": [], "sleep": [], "text": _truncate(json.dumps(data, ensure_ascii=False))}

    # .fit и всё прочее бинарное здесь не разбираем — просим экспорт в CSV/JSON.
    if lower.endswith(".fit"):
        raise ValueError(
            "Файлы .fit пока не поддерживаются — выгрузи активность в CSV или пришли скриншот."
        )

    return {"workouts": [], "sleep": [], "text": _truncate(content)}


# --------------------------------------------------------------------- CSV


def _parse_activity_csv(content: str) -> list[dict[str, Any]]:
    dialect_delim = "\t" if content.count("\t") > content.count(",") else ","
    reader = csv.DictReader(io.StringIO(content), delimiter=dialect_delim)
    if not reader.fieldnames:
        return []

    mapping = _map_columns(reader.fieldnames)
    if "date" not in mapping or "kind" not in mapping:
        return []

    workouts: list[dict[str, Any]] = []
    for row in reader:
        kind_raw = (row.get(mapping["kind"]) or "").strip()
        parsed_date = _parse_date(row.get(mapping["date"]))
        if not parsed_date:
            continue
        workouts.append(
            {
                "date": parsed_date,
                "kind": _classify(kind_raw),
                "title": (row.get(mapping.get("title", "")) or kind_raw or None),
                "duration_min": _duration_min(row.get(mapping.get("duration", ""))),
                "distance_km": _number(row.get(mapping.get("distance", ""))),
                "avg_hr": _number(row.get(mapping.get("avg_hr", ""))),
                "max_hr": _number(row.get(mapping.get("max_hr", ""))),
                "exercises": [],
                "notes": None,
            }
        )
    return workouts


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field in fieldnames:
        key = field.strip().lower()
        for canonical, variants in _ACTIVITY_COLUMNS.items():
            if canonical in mapping:
                continue
            if key in variants or any(key.startswith(v) for v in variants):
                mapping[canonical] = field
                break
    return mapping


def _classify(value: str) -> str:
    low = value.lower()
    if any(h in low for h in _STRENGTH_HINTS):
        return "strength"
    if any(h in low for h in _CARDIO_HINTS):
        return "cardio"
    return "other"


# -------------------------------------------------------------------- JSON


_SLEEP_KEYS = {
    "total_min": ("sleepTimeSeconds", "totalSleepSeconds", "sleepDurationSeconds"),
    "deep_min": ("deepSleepSeconds", "deepSleepDurationSeconds"),
    "rem_min": ("remSleepSeconds", "remSleepDurationSeconds"),
    "light_min": ("lightSleepSeconds", "lightSleepDurationSeconds"),
    "awake_min": ("awakeSleepSeconds", "awakeDurationSeconds"),
    "score": ("sleepScore", "overallSleepScore", "score"),
    "resting_hr": ("restingHeartRate", "restingHR"),
    "hrv_ms": ("avgOvernightHrv", "hrvWeeklyAverage", "avgHrv"),
    "body_battery": ("bodyBatteryChange", "bodyBatteryHigh"),
    "stress_avg": ("avgStressLevel", "averageStressLevel"),
    "spo2": ("averageSpO2", "averageSpo2Value"),
}


def _parse_sleep_json(data: Any) -> list[dict[str, Any]]:
    records = data if isinstance(data, list) else [data]
    nights: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        flat = _flatten(record)
        night: dict[str, Any] = {}
        for canonical, keys in _SLEEP_KEYS.items():
            for key in keys:
                if key in flat and flat[key] is not None:
                    value = _number(flat[key])
                    if value is None:
                        continue
                    night[canonical] = value / 60 if key.endswith("Seconds") else value
                    break
        night_date = _find_date(flat)
        if night_date and night.get("total_min"):
            night["date"] = night_date
            nights.append(night)
    return nights


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, prefix))
        else:
            flat[key] = value
    return flat


def _find_date(flat: dict[str, Any]) -> str | None:
    for key in ("calendarDate", "sleepEndDate", "date", "startTimeLocal", "sleepStartTimestampLocal"):
        if key in flat:
            parsed = _parse_date(flat[key])
            if parsed:
                return parsed
    return None


# ------------------------------------------------------------------ helpers


def _parse_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):  # epoch в миллисекундах
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds).date().isoformat()
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return match.group(0)
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", ".").replace(" ", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None


def _duration_min(value: Any) -> float | None:
    """'01:23:45' -> 83.75; '45 min' -> 45."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if ":" in text:
        parts = [float(p) for p in text.split(":") if p != ""]
        if len(parts) == 3:
            return round(parts[0] * 60 + parts[1] + parts[2] / 60, 2)
        if len(parts) == 2:
            return round(parts[0] + parts[1] / 60, 2)
    return _number(text)


def _truncate(text: str) -> str:
    return text[:MAX_LLM_CHARS]
