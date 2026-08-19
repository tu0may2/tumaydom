import pytest

from fitcoach.ingest.files import load_file, _duration_min, _parse_date


def test_garmin_activity_csv():
    blob = (
        b"Activity Type,Date,Title,Distance,Time,Avg HR,Max HR\n"
        b"Running,2026-08-18 07:12:00,Morning Run,10.2,00:52:30,148,171\n"
        b"Strength Training,17.08.2026,Push A,,01:05:00,112,155\n"
    )
    result = load_file("activities.csv", blob)
    assert result["text"] is None
    run, strength = result["workouts"]
    assert run["kind"] == "cardio" and run["distance_km"] == 10.2
    assert run["duration_min"] == 52.5
    assert strength["kind"] == "strength" and strength["date"] == "2026-08-17"


def test_sleep_json_converts_seconds_to_minutes():
    blob = (
        b'[{"calendarDate":"2026-08-18","sleepTimeSeconds":25920,'
        b'"sleepScores":{"overallSleepScore":81},"restingHeartRate":48}]'
    )
    night = load_file("sleep.json", blob)["sleep"][0]
    assert night["total_min"] == 432.0
    assert night["score"] == 81
    assert night["resting_hr"] == 48


def test_unknown_csv_falls_back_to_text():
    result = load_file("random.csv", b"foo,bar\n1,2\n")
    assert result["text"] is not None
    assert result["workouts"] == []


def test_fit_is_rejected_with_hint():
    with pytest.raises(ValueError, match="fit"):
        load_file("activity.fit", b"\x00\x01")


@pytest.mark.parametrize(
    "value,expected",
    [("01:23:45", 83.75), ("45:00", 45.0), ("45 min", 45.0), ("", None)],
)
def test_duration_parsing(value, expected):
    assert _duration_min(value) == expected


def test_epoch_millis_date():
    assert _parse_date(1755500000000) is not None
