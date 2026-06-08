from datetime import date

from midnight_routine import _build_cron_expr, _build_once_at, _expand_schedule_hours


def test_build_cron_expr_for_specific_hours():
    assert _build_cron_expr(9, [12, 15, 18]) == "0 9,12,15,18 * * *"


def test_build_cron_expr_for_hour_range():
    assert _build_cron_expr(9, 18) == "0 9-18 * * *"


def test_expand_schedule_hours_for_specific_hours():
    assert _expand_schedule_hours(9, [12, 15, 18]) == [9, 12, 15, 18]


def test_expand_schedule_hours_for_hour_range():
    assert _expand_schedule_hours(9, 12) == [9, 10, 11, 12]


def test_build_once_at_uses_kuala_lumpur_offset():
    assert _build_once_at(date(2026, 6, 8), 9) == "2026-06-08T09:00:00+08:00"
