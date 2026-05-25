from midnight_routine import _build_cron_expr


def test_build_cron_expr_for_specific_hours():
    assert _build_cron_expr(9, [12, 15, 18]) == "0 9,12,15,18 * * *"


def test_build_cron_expr_for_hour_range():
    assert _build_cron_expr(9, 18) == "0 9-18 * * *"
