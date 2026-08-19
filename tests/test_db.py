from fitcoach.db import Database, tonnage


def test_tonnage_sums_weight_times_reps():
    exercises = [
        {"name": "жим", "sets": [{"weight_kg": 80, "reps": 5}] * 5},
        {"name": "тяга", "sets": [{"weight_kg": 100, "reps": 3}, {"weight_kg": None, "reps": 10}]},
    ]
    assert tonnage(exercises) == 2000.0 + 300.0


def test_workout_roundtrip(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_workout(1, {"date": "2026-08-18", "kind": "strength",
                       "exercises": [{"name": "присед", "sets": [{"weight_kg": 100, "reps": 5}]}]})
    workouts = db.recent_workouts(1)
    assert len(workouts) == 1
    assert workouts[0]["tonnage_kg"] == 500.0
    assert workouts[0]["exercises"][0]["name"] == "присед"


def test_sleep_upsert_replaces_same_date(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_sleep(1, {"date": "2026-08-18", "total_min": 400})
    db.add_sleep(1, {"date": "2026-08-18", "total_min": 430, "score": 80})
    nights = db.recent_sleep(1)
    assert len(nights) == 1
    assert nights[0]["total_min"] == 430


def test_profile_patch_merges(tmp_path):
    db = Database(tmp_path / "t.db")
    db.update_profile(1, {"goal": "сила", "weight_kg": 82}, chat_id=5)
    db.update_profile(1, {"weight_kg": 81.4})
    profile = db.get_profile(1)
    assert profile == {"goal": "сила", "weight_kg": 81.4}
    assert db.subscribers() == [(1, 5)]
