from fitcoach.analysis.progress import e1rm, exercise_progress, flags, weekly_factors

WORKOUTS = [
    {"date": "2026-08-18", "kind": "strength", "tonnage_kg": 2500, "rpe": 9,
     "exercises": [{"name": "Присед", "sets": [{"weight_kg": 100, "reps": 5}] * 5}]},
    {"date": "2026-08-11", "kind": "strength", "tonnage_kg": 1000, "rpe": 7,
     "exercises": [{"name": "присед", "sets": [{"weight_kg": 90, "reps": 5}] * 2}]},
]
NIGHTS = [
    {"date": "2026-08-18", "total_min": 360, "hrv_ms": 50},
    {"date": "2026-08-11", "total_min": 460, "hrv_ms": 65},
]
METRICS = [{"date": "2026-08-18", "name": "weight_kg", "value": 82.0}]


def test_e1rm_epley():
    assert e1rm(100, 5) == 116.7
    assert e1rm(100, 1) == 103.3


def test_exercise_progress_is_case_insensitive_and_tracks_growth():
    rows = exercise_progress(WORKOUTS)
    assert len(rows) == 1
    row = rows[0]
    assert row["exercise"] == "присед"
    assert row["sessions"] == 2
    assert row["best_set"] == "100×5"
    assert row["change_kg"] == 11.7
    assert row["change_pct"] == 11.1


def test_exercise_progress_skips_sets_without_numbers():
    rows = exercise_progress([
        {"date": "2026-08-18", "exercises": [{"name": "планка",
                                              "sets": [{"duration_sec": 60}]}]}
    ])
    assert rows == []


def test_weekly_factors_joins_load_and_recovery():
    rows = weekly_factors(WORKOUTS, NIGHTS, METRICS)
    current = rows[0]
    assert current["week_start"] == "2026-08-17"
    assert current["tonnage_kg"] == 2500
    assert current["avg_sleep_min"] == 360
    assert current["avg_hrv_ms"] == 50
    assert current["avg_weight_kg"] == 82.0
    assert current["tonnage_change_pct"] == 150.0


def test_flags_catch_overload_and_poor_recovery():
    notes = " ".join(flags(weekly_factors(WORKOUTS, NIGHTS, METRICS)))
    assert "Объём вырос" in notes
    assert "HRV" in notes
    assert "RPE" in notes


def test_flags_need_two_weeks():
    assert flags([{"week_start": "2026-08-17", "tonnage_kg": 100}]) == []
