import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.result_panel import (
    RISK_LABELS_KR,
    RISK_THRESHOLDS,
    render_risk_badges,
    render_top3_gauges,
)

# 계획서 Task 6은 위험도 키를 pattern / extra_base / home_run / walk 로 적었지만
# 실제 데이터 키는 _risk 접미가 붙는다. 계획서 쪽이 오기이고 코드가 진실이다.
REAL_RISK_KEYS = {
    "pattern_exposure_risk", "extra_base_hit_risk", "home_run_risk", "walk_risk",
}


def test_risk_labels_and_thresholds_use_the_real_keys():
    """키가 어긋나면 risk_level이 KeyError를 낸다. 여기서 먼저 못을 박아둔다."""
    assert set(RISK_LABELS_KR) == REAL_RISK_KEYS
    assert set(RISK_THRESHOLDS) == REAL_RISK_KEYS


def test_risk_badges_render_all_four_in_one_row():
    summary = {
        "pattern_exposure_risk": 0.319, "extra_base_hit_risk": 0.042,
        "home_run_risk": 0.017, "walk_risk": 0.104,
    }

    html = render_risk_badges(summary)

    assert html.count("ds-risk__label") == 4
    assert "ds-risks" in html


def test_risk_badges_handle_missing_value():
    """값이 없는 위험도도 예외 없이, 4개 전부 렌더되어야 한다."""
    html = render_risk_badges({"pattern_exposure_risk": 0.3})

    assert html.count("ds-risk__label") == 4
    assert "데이터 부족" in html


def test_risk_badges_shorten_labels_but_reports_keep_the_full_wording():
    """배지는 4칸을 나눠 쓰므로 "패턴 노출 위험"이 들어가면 넘친다.
    리포트가 쓰는 RISK_LABELS_KR 원본은 건드리지 않는다."""
    html = render_risk_badges({"pattern_exposure_risk": 0.3})

    assert ">패턴 노출<" in html
    assert "패턴 노출 위험" not in html
    assert RISK_LABELS_KR["pattern_exposure_risk"] == "패턴 노출 위험"


def test_risk_badges_show_level_and_percent():
    html = render_risk_badges({"home_run_risk": 0.017})

    assert "낮음" in html
    assert "1.7%" in html


def test_top3_gauges_render_three_bars_in_order():
    top3 = [
        {"pitch_label": "FF", "probability": 0.317},
        {"pitch_label": "SL", "probability": 0.268},
        {"pitch_label": "CU", "probability": 0.131},
    ]

    html = render_top3_gauges(top3)

    assert html.count("ds-track__fill") == 3
    assert html.index("포심") < html.index("슬라이더") < html.index("커브")


def test_top3_gauge_shows_probability_as_percent():
    html = render_top3_gauges([{"pitch_label": "FF", "probability": 0.317}])

    assert "31.7%" in html


def test_top3_first_rank_gets_emphasis_class():
    top3 = [
        {"pitch_label": "FF", "probability": 0.317},
        {"pitch_label": "SL", "probability": 0.268},
    ]

    assert render_top3_gauges(top3).count("ds-rank--1") == 1


def test_top3_bar_widths_are_relative_to_the_top_item():
    """1위가 항상 꽉 찬 막대여야 순위 차이가 눈에 들어온다."""
    html = render_top3_gauges([
        {"pitch_label": "FF", "probability": 0.40},
        {"pitch_label": "SL", "probability": 0.20},
    ]).replace(" ", "")

    assert "width:100%" in html
    assert "width:50%" in html


def test_top3_gauges_tolerate_fewer_than_three_items():
    assert render_top3_gauges([]).count("ds-track__fill") == 0
    assert render_top3_gauges([{"pitch_label": "FF", "probability": 0.3}]).count("ds-track__fill") == 1
