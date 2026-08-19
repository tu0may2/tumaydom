from fitcoach.db import Database
from fitcoach.ingest.parser import apply_ingest


def test_apply_ingest_saves_all_entities(tmp_path):
    db = Database(tmp_path / "t.db")
    parsed = {
        "intent": "workout",
        "workouts": [{"date": "2026-08-18", "kind": "strength",
                      "exercises": [{"name": "жим", "sets": [{"weight_kg": 80, "reps": 5}]}]}],
        "sleep": [{"date": "2026-08-18", "total_min": 430}],
        "metrics": [{"date": "2026-08-18", "name": "weight_kg", "value": 82.4},
                    {"date": "2026-08-18", "name": None, "value": 5}],
        "profile_patch": {"goal": "сила", "height_cm": None},
    }
    counts = apply_ingest(db, 1, parsed, source="text", raw="жим 80x5")

    assert counts == {"workouts": 1, "sleep": 1, "metrics": 1, "profile": 1}
    assert db.recent_workouts(1)[0]["source"] == "text"
    assert db.get_profile(1) == {"goal": "сила"}


def test_apply_ingest_on_empty_payload(tmp_path):
    db = Database(tmp_path / "t.db")
    counts = apply_ingest(db, 1, {"intent": "question"}, source="text")
    assert counts == {"workouts": 0, "sleep": 0, "metrics": 0, "profile": 0}
