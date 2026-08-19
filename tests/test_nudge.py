from fitcoach.db import Database
from fitcoach.scheduler import _nudge_text


def test_nudge_mentions_planned_session():
    text = _nudge_text({"kind": "strength", "title": "Ноги A", "blocks": ["присед 100x5x5"]})
    assert "Ноги A" in text and "присед 100x5x5" in text


def test_nudge_on_rest_day_does_not_demand_report():
    text = _nudge_text({"kind": "rest", "title": "Отдых"})
    assert "отдых" in text.lower()
    assert "Тренировался?" not in text


def test_nudge_without_plan_asks_generally():
    assert "тренировался" in _nudge_text(None).lower()


def test_workouts_on_filters_by_day(tmp_path):
    db = Database(tmp_path / "t.db")
    db.add_workout(1, {"date": "2026-08-18", "kind": "strength"})
    assert len(db.workouts_on(1, "2026-08-18")) == 1
    assert db.workouts_on(1, "2026-08-19") == []


def test_sent_today_prevents_double_nudge(tmp_path):
    db = Database(tmp_path / "t.db")
    assert db.sent_today(1, "nudge") is False
    db.log_message(1, "nudge", "тренировался?")
    assert db.sent_today(1, "nudge") is True
    assert db.sent_today(1, "morning") is False
