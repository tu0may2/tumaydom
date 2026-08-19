"""Прогресс по упражнениям и связки «нагрузка ↔ восстановление ↔ результат».

Всё считается кодом: модель потом объясняет цифры, но не выдумывает их.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Any

from .stats import week_start


def e1rm(weight: float, reps: float) -> float:
    """Оценка одноповторного максимума по Эпли."""
    return round(weight * (1 + reps / 30), 1)


def exercise_progress(workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """По каждому упражнению: лучший подход, оценка 1ПМ и её сдвиг за период."""
    history: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for workout in workouts:
        for exercise in workout.get("exercises") or []:
            name = (exercise.get("name") or "").strip().lower()
            if not name:
                continue
            best = None
            volume = 0.0
            reps_total = 0
            for st in exercise.get("sets") or []:
                weight, reps = st.get("weight_kg"), st.get("reps")
                if not weight or not reps:
                    continue
                volume += float(weight) * float(reps)
                reps_total += int(reps)
                estimate = e1rm(float(weight), float(reps))
                if best is None or estimate > best["e1rm"]:
                    best = {"weight_kg": float(weight), "reps": int(reps), "e1rm": estimate}
            if best:
                history[name].append({"date": workout.get("date"), "volume_kg": round(volume, 1),
                                      "reps": reps_total, **best})

    rows = []
    for name, points in history.items():
        points.sort(key=lambda p: p["date"] or "")
        first, last = points[0], points[-1]
        peak = max(points, key=lambda p: p["e1rm"])
        rows.append(
            {
                "exercise": name,
                "sessions": len(points),
                "first_date": first["date"],
                "last_date": last["date"],
                "first_e1rm": first["e1rm"],
                "last_e1rm": last["e1rm"],
                "best_e1rm": peak["e1rm"],
                "best_set": f"{peak['weight_kg']:g}×{peak['reps']}",
                "change_kg": round(last["e1rm"] - first["e1rm"], 1),
                "change_pct": round((last["e1rm"] / first["e1rm"] - 1) * 100, 1)
                if first["e1rm"] else 0.0,
                "last_volume_kg": last["volume_kg"],
            }
        )
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return rows


def weekly_factors(
    workouts: list[dict[str, Any]],
    nights: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    weeks: int = 12,
) -> list[dict[str, Any]]:
    """Неделя за неделей: объём, RPE, сон, HRV, вес — рядом, чтобы видеть связи."""
    by_week: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    def bucket(value: Any) -> str | None:
        try:
            return week_start(date.fromisoformat(value)).isoformat()
        except (ValueError, TypeError):
            return None

    for workout in workouts:
        key = bucket(workout.get("date"))
        if not key:
            continue
        by_week[key]["sessions"].append(1)
        by_week[key]["tonnage"].append(float(workout.get("tonnage_kg") or 0))
        by_week[key]["distance"].append(float(workout.get("distance_km") or 0))
        by_week[key]["duration"].append(float(workout.get("duration_min") or 0))
        if workout.get("rpe"):
            by_week[key]["rpe"].append(float(workout["rpe"]))

    for night in nights:
        key = bucket(night.get("date"))
        if not key:
            continue
        for field, target in (("total_min", "sleep"), ("score", "sleep_score"),
                              ("hrv_ms", "hrv"), ("resting_hr", "rhr")):
            if night.get(field) is not None:
                by_week[key][target].append(float(night[field]))

    for metric in metrics:
        if metric.get("name") != "weight_kg":
            continue
        key = bucket(metric.get("date"))
        if key:
            by_week[key]["weight"].append(float(metric["value"]))

    rows = []
    for key in sorted(by_week, reverse=True)[:weeks]:
        data = by_week[key]
        rows.append(
            {
                "week_start": key,
                "sessions": len(data["sessions"]),
                "tonnage_kg": round(sum(data["tonnage"]), 1),
                "distance_km": round(sum(data["distance"]), 2),
                "duration_min": round(sum(data["duration"]), 1),
                "avg_rpe": round(mean(data["rpe"]), 2) if data["rpe"] else None,
                "avg_sleep_min": round(mean(data["sleep"]), 1) if data["sleep"] else None,
                "avg_sleep_score": round(mean(data["sleep_score"]), 1)
                if data["sleep_score"] else None,
                "avg_hrv_ms": round(mean(data["hrv"]), 1) if data["hrv"] else None,
                "avg_resting_hr": round(mean(data["rhr"]), 1) if data["rhr"] else None,
                "avg_weight_kg": round(mean(data["weight"]), 2) if data["weight"] else None,
            }
        )

    # Сдвиг объёма к предыдущей неделе — главный признак перегруза или провала.
    ordered = sorted(rows, key=lambda r: r["week_start"])
    previous = None
    for row in ordered:
        if previous and previous["tonnage_kg"]:
            row["tonnage_change_pct"] = round(
                (row["tonnage_kg"] / previous["tonnage_kg"] - 1) * 100, 1
            )
        else:
            row["tonnage_change_pct"] = None
        previous = row
    return rows


def flags(factors: list[dict[str, Any]]) -> list[str]:
    """Простые эвристики: то, на что стоит посмотреть в первую очередь."""
    notes: list[str] = []
    if len(factors) < 2:
        return notes

    ordered = sorted(factors, key=lambda r: r["week_start"])
    current, previous = ordered[-1], ordered[-2]

    change = current.get("tonnage_change_pct")
    if change is not None and change > 20:
        notes.append(f"Объём вырос на {change:g}% за неделю — это выше безопасных ~10%.")
    if change is not None and change < -25:
        notes.append(f"Объём упал на {abs(change):g}% — пропуски или сознательная разгрузка?")

    if current.get("avg_sleep_min") and current["avg_sleep_min"] < 390:
        notes.append(
            f"Средний сон {current['avg_sleep_min'] / 60:.1f} ч — ниже 6.5 ч, "
            "восстановление под нагрузкой страдает."
        )

    for field, label in (("avg_hrv_ms", "HRV"), ("avg_resting_hr", "пульс покоя")):
        now, before = current.get(field), previous.get(field)
        if now and before:
            delta_pct = (now / before - 1) * 100
            if field == "avg_hrv_ms" and delta_pct < -10:
                notes.append(f"{label} упал на {abs(delta_pct):.0f}% к прошлой неделе.")
            if field == "avg_resting_hr" and delta_pct > 7:
                notes.append(f"{label} вырос на {delta_pct:.0f}% — признак недовосстановления.")

    if current.get("avg_rpe") and current["avg_rpe"] >= 8.5:
        notes.append(f"Средний RPE {current['avg_rpe']} — неделя шла почти на отказ.")

    return notes


def pace_min_km(workout: dict[str, Any]) -> float | None:
    """Темп в минутах на километр."""
    distance = workout.get("distance_km")
    duration = workout.get("duration_min")
    if not distance or not duration:
        return None
    return round(float(duration) / float(distance), 2)


def format_pace(value: float | None) -> str | None:
    """4.75 -> '4:45'."""
    if value is None:
        return None
    minutes = int(value)
    seconds = round((value - minutes) * 60)
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d}"


def _best_set(exercise: dict[str, Any]) -> dict[str, Any] | None:
    best = None
    for st in exercise.get("sets") or []:
        weight, reps = st.get("weight_kg"), st.get("reps")
        if not weight or not reps:
            continue
        estimate = e1rm(float(weight), float(reps))
        if best is None or estimate > best["e1rm"]:
            best = {"weight_kg": float(weight), "reps": int(reps), "e1rm": estimate}
    return best


def _volume(exercise: dict[str, Any]) -> float:
    return round(sum(
        float(st["weight_kg"]) * float(st["reps"])
        for st in exercise.get("sets") or []
        if st.get("weight_kg") and st.get("reps")
    ), 1)


def compare_workout(history: list[dict[str, Any]], workout: dict[str, Any]) -> dict[str, Any]:
    """Сравнить свежую тренировку с прошлыми: по каждому упражнению и по кардио.

    `history` — прошлые тренировки (без этой). Возвращает готовые цифры,
    чтобы модель их объясняла, а не считала.
    """
    result: dict[str, Any] = {"exercises": [], "cardio": None, "personal_records": []}

    # --- силовая часть: упражнение за упражнением против прошлого раза и рекорда
    past: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for old in history:
        for exercise in old.get("exercises") or []:
            name = (exercise.get("name") or "").strip().lower()
            best = _best_set(exercise)
            if name and best:
                past[name].append({"date": old.get("date"), "volume_kg": _volume(exercise),
                                   **best})

    for exercise in workout.get("exercises") or []:
        name = (exercise.get("name") or "").strip().lower()
        best = _best_set(exercise)
        if not name or not best:
            continue

        entry: dict[str, Any] = {
            "exercise": name,
            "sets": [
                {"weight_kg": st.get("weight_kg"), "reps": st.get("reps"), "rpe": st.get("rpe")}
                for st in exercise.get("sets") or []
            ],
            "best_set": f"{best['weight_kg']:g}×{best['reps']}",
            "e1rm": best["e1rm"],
            "volume_kg": _volume(exercise),
        }

        previous = sorted(past.get(name, []), key=lambda p: p["date"] or "")
        if previous:
            last = previous[-1]
            record = max(previous, key=lambda p: p["e1rm"])
            entry.update({
                "previous_date": last["date"],
                "previous_best_set": f"{last['weight_kg']:g}×{last['reps']}",
                "previous_e1rm": last["e1rm"],
                "e1rm_change": round(best["e1rm"] - last["e1rm"], 1),
                "volume_change_kg": round(entry["volume_kg"] - last["volume_kg"], 1),
                "record_e1rm": record["e1rm"],
                "sessions_before": len(previous),
            })
            if best["e1rm"] > record["e1rm"]:
                entry["is_record"] = True
                result["personal_records"].append(
                    f"{name}: {entry['best_set']} (оценка 1ПМ {best['e1rm']} кг, "
                    f"прошлый рекорд {record['e1rm']})"
                )
        else:
            entry["first_time"] = True

        result["exercises"].append(entry)

    # --- кардио: темп против прошлых пробежек похожей длины
    pace = pace_min_km(workout)
    if pace:
        distance = float(workout["distance_km"])
        similar = [
            {"date": old.get("date"), "distance_km": old.get("distance_km"),
             "pace": pace_min_km(old), "avg_hr": old.get("avg_hr")}
            for old in history
            if old.get("kind") == "cardio" and pace_min_km(old)
            and abs(float(old["distance_km"]) - distance) <= max(1.0, distance * 0.25)
        ]
        similar.sort(key=lambda item: item["date"] or "")
        cardio: dict[str, Any] = {
            "distance_km": distance,
            "pace_min_km": pace,
            "pace_text": format_pace(pace),
            "avg_hr": workout.get("avg_hr"),
            "comparable_sessions": len(similar),
        }
        if similar:
            last = similar[-1]
            fastest = min(similar, key=lambda item: item["pace"])
            cardio.update({
                "previous_date": last["date"],
                "previous_pace": format_pace(last["pace"]),
                "pace_change_sec_km": round((pace - last["pace"]) * 60),
                "previous_avg_hr": last["avg_hr"],
                "best_pace": format_pace(fastest["pace"]),
            })
            if pace < fastest["pace"]:
                cardio["is_record"] = True
                result["personal_records"].append(
                    f"бег {distance:g} км: {format_pace(pace)} /км "
                    f"(прошлый лучший {format_pace(fastest['pace'])})"
                )
        result["cardio"] = cardio

    return result


def cardio_progress(workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Кардио по дистанциям: лучший и последний темп в каждой группе."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for workout in workouts:
        pace = pace_min_km(workout)
        if workout.get("kind") != "cardio" or not pace:
            continue
        distance = float(workout["distance_km"])
        label = "до 5 км" if distance < 5 else "5–10 км" if distance < 10 else "10+ км"
        buckets[label].append({"date": workout.get("date"), "pace": pace,
                               "distance_km": distance, "avg_hr": workout.get("avg_hr")})

    rows = []
    for label, items in buckets.items():
        items.sort(key=lambda item: item["date"] or "")
        fastest = min(items, key=lambda item: item["pace"])
        rows.append({
            "bucket": label,
            "sessions": len(items),
            "last_pace": format_pace(items[-1]["pace"]),
            "last_date": items[-1]["date"],
            "best_pace": format_pace(fastest["pace"]),
            "best_date": fastest["date"],
            "change_sec_km": round((items[-1]["pace"] - items[0]["pace"]) * 60),
        })
    rows.sort(key=lambda row: row["bucket"])
    return rows
