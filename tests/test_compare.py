from fitcoach.analysis.coach import progress_report
from fitcoach.analysis.progress import (
    cardio_progress,
    compare_workout,
    format_pace,
    pace_min_km,
)
from fitcoach.db import Database

HISTORY = [
    {"date": "2026-08-11", "kind": "strength",
     "exercises": [{"name": "присед", "sets": [{"weight_kg": 90, "reps": 5}] * 4}]},
    {"date": "2026-08-04", "kind": "cardio", "distance_km": 10, "duration_min": 55},
    {"date": "2026-08-12", "kind": "cardio", "distance_km": 10, "duration_min": 52},
]


def test_pace_helpers():
    assert pace_min_km({"distance_km": 10, "duration_min": 52.5}) == 5.25
    assert pace_min_km({"distance_km": 0, "duration_min": 30}) is None
    assert format_pace(5.25) == "5:15"
    assert format_pace(4.999) == "5:00"  # округление секунд не даёт «4:60»


def test_compare_detects_strength_record():
    workout = {"date": "2026-08-18", "kind": "strength",
               "exercises": [{"name": "Присед", "sets": [{"weight_kg": 100, "reps": 5}] * 4}]}
    result = compare_workout(HISTORY, workout)
    entry = result["exercises"][0]

    assert entry["best_set"] == "100×5"
    assert entry["previous_best_set"] == "90×5"
    assert entry["e1rm_change"] == 11.7
    assert entry["volume_change_kg"] == 200.0
    assert entry.get("is_record") is True
    assert result["personal_records"]


def test_compare_marks_new_exercise():
    workout = {"date": "2026-08-18", "exercises": [
        {"name": "тяга", "sets": [{"weight_kg": 60, "reps": 8}]}]}
    entry = compare_workout(HISTORY, workout)["exercises"][0]
    assert entry.get("first_time") is True
    assert "previous_e1rm" not in entry


def test_compare_cardio_against_similar_distance():
    run = {"date": "2026-08-19", "kind": "cardio", "distance_km": 10,
           "duration_min": 50, "avg_hr": 150}
    cardio = compare_workout(HISTORY, run)["cardio"]

    assert cardio["pace_text"] == "5:00"
    assert cardio["comparable_sessions"] == 2
    assert cardio["pace_change_sec_km"] == -12  # быстрее прошлого раза
    assert cardio.get("is_record") is True


def test_compare_ignores_far_distances():
    sprint = {"date": "2026-08-19", "kind": "cardio", "distance_km": 2, "duration_min": 10}
    assert compare_workout(HISTORY, sprint)["cardio"]["comparable_sessions"] == 0


def test_cardio_progress_buckets_by_distance():
    rows = cardio_progress(HISTORY)
    assert len(rows) == 1
    assert rows[0]["bucket"] == "10+ км"
    assert rows[0]["best_pace"] == "5:12"
    assert rows[0]["change_sec_km"] == -18


def test_progress_report_text(tmp_path):
    db = Database(tmp_path / "t.db")
    for day, weight in (("2026-07-01", 90), ("2026-08-01", 100)):
        db.add_workout(1, {"date": day, "kind": "strength",
                           "exercises": [{"name": "присед",
                                          "sets": [{"weight_kg": weight, "reps": 5}] * 4}]})
    report = progress_report(db, 1)
    assert "присед" in report
    assert "116.7" in report


def test_progress_report_without_data(tmp_path):
    db = Database(tmp_path / "t.db")
    assert "Данных пока нет" in progress_report(db, 1)
