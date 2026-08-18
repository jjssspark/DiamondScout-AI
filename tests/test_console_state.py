import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.console import (
    MAX_BALLS, MAX_OUTS, MAX_STRIKES,
    cycle_value, render_base_diamond, render_count_lamps, toggle_base,
)


def test_cycle_value_increments_within_range():
    assert cycle_value(0, MAX_BALLS) == 1
    assert cycle_value(2, MAX_BALLS) == 3


def test_cycle_value_wraps_to_zero_at_maximum():
    """볼 3에서 한 번 더 누르면 0으로 돌아간다 — 잘못 눌러도 되돌릴 수 있어야 한다."""
    assert cycle_value(MAX_BALLS, MAX_BALLS) == 0
    assert cycle_value(MAX_STRIKES, MAX_STRIKES) == 0
    assert cycle_value(MAX_OUTS, MAX_OUTS) == 0


def test_toggle_base_turns_runner_on():
    assert toggle_base((0, 0, 0), 0) == (1, 0, 0)


def test_toggle_base_turns_runner_off():
    assert toggle_base((1, 1, 0), 1) == (1, 0, 0)


def test_toggle_base_does_not_touch_other_bases():
    assert toggle_base((1, 0, 1), 1) == (1, 1, 1)


def test_toggle_base_does_not_mutate_input():
    """불변 패턴 — 입력 튜플이 그대로여야 한다."""
    original = (1, 0, 0)
    toggle_base(original, 1)

    assert original == (1, 0, 0)


def test_count_lamps_marks_filled_and_empty():
    html = render_count_lamps(balls=2, strikes=1, outs=0)

    assert html.count("ds-lamp--on") == 3      # 볼 2 + 스트라이크 1
    assert html.count("ds-lamp--off") == 7     # 램프 총 10개(볼4+스트라이크3+아웃3) - on 3개


def test_base_diamond_marks_occupied_bases():
    html = render_base_diamond(on1b=1, on2b=0, on3b=1)

    assert html.count("ds-base--occupied") == 2


def test_renderers_return_html_string():
    assert render_count_lamps(0, 0, 0).lstrip().startswith("<")
    assert render_base_diamond(0, 0, 0).lstrip().startswith("<")
