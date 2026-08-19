from fitcoach.analysis.stats import sleep_trend, weekly_summary, week_start
from datetime import date


def test_week_start_is_monday():
    assert week_start(date(2026, 8, 19)).weekday() == 0


def test_weekly_summary_buckets_by_week():
    workouts = [
        {"date": "2026-08-18", "kind": "strength", "tonnage_kg": 5000, "rpe": 8,
         "duration_min": 60},
        {"date": "2026-08-17", "kind": "cardio", "distance_km": 10, "rpe": 6,
         "duration_min": 50},
        {"date": "2026-08-11", "kind": "strength", "tonnage_kg": 4000, "rpe": 7},
    ]
    weeks = weekly_summary(workouts)
    assert len(weeks) == 2
    current = weeks[0]
    assert current["sessions"] == 2
    assert current["tonnage_kg"] == 5000
    assert current["distance_km"] == 10
    assert current["avg_rpe"] == 7.0


def test_weekly_summary_skips_broken_dates():
    assert weekly_summary([{"date": None, "kind": "strength"}]) == []


def test_sleep_trend_delta_against_week_average():
    nights = [
        {"date": "2026-08-19", "total_min": 360, "score": 60},
        {"date": "2026-08-18", "total_min": 480, "score": 80},
    ]
    trend = sleep_trend(nights)
    assert trend["avg_7d"]["total_min"] == 420.0
    assert trend["delta"]["total_min"] == -60.0


def test_sleep_trend_handles_empty():
    assert sleep_trend([])["last"] is None
