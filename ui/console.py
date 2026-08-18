"""덕아웃 콘솔 게임 컨트롤 렌더러.

HTML은 표시 전용이다. 값의 단일 진실 공급원은 Gradio state이며,
클릭 이벤트가 state를 바꾸고 state가 여기 함수들을 다시 호출해 HTML을 갱신한다.
"""

import html

MAX_BALLS = 3
MAX_STRIKES = 2
MAX_OUTS = 2

# 단계 흐름. 한 화면에 다 펼치면 밀도가 높아 어디부터 봐야 할지 모르겠다는
# 피드백을 받아 세 단계로 나눴다. 컴포넌트는 그대로 두고 보이는 범위만 나눈다.
STEP_LABELS = ["매치업", "상황", "결과"]


def cycle_value(current: int, maximum: int) -> int:
    """최대치에서 한 번 더 누르면 0으로 돌아간다 — 잘못 눌러도 되돌릴 수 있어야 한다."""
    return 0 if current >= maximum else current + 1


def toggle_base(bases: tuple[int, int, int], index: int) -> tuple[int, int, int]:
    """지정한 베이스의 주자 유무만 뒤집은 새 튜플을 반환한다 (입력을 변형하지 않는다)."""
    updated = list(bases)
    updated[index] = 0 if updated[index] else 1
    return tuple(updated)


def _lamps(filled: int, total: int, kind: str) -> str:
    return "".join(
        f'<span class="ds-lamp ds-lamp--{"on" if i < filled else "off"}"'
        f' data-kind="{kind}" data-index="{i}"></span>'
        for i in range(total)
    )


def render_count_lamps(balls: int, strikes: int, outs: int) -> str:
    """볼·스트라이크·아웃을 불 형태로 그린다. 슬라이더 3개를 대체한다."""
    return f"""
<div class="ds-count-lamps">
  <div class="ds-lamp-group"><span class="ds-lamp-label">B</span>{_lamps(balls, MAX_BALLS + 1, "balls")}</div>
  <div class="ds-lamp-group"><span class="ds-lamp-label">S</span>{_lamps(strikes, MAX_STRIKES + 1, "strikes")}</div>
  <div class="ds-lamp-group"><span class="ds-lamp-label">O</span>{_lamps(outs, MAX_OUTS + 1, "outs")}</div>
</div>
""".strip()


def render_base_diamond(on1b: int, on2b: int, on3b: int) -> str:
    """다이아몬드 그림. 체크박스 3개를 대체한다."""

    def cls(occupied: int) -> str:
        return "ds-base ds-base--occupied" if occupied else "ds-base"

    return f"""
<div class="ds-diamond" role="group" aria-label="주자 상황">
  <svg viewBox="0 0 120 120" class="ds-diamond-svg">
    <rect class="{cls(on2b)}" x="52" y="12" width="16" height="16" transform="rotate(45 60 20)"  data-base="2"/>
    <rect class="{cls(on1b)}" x="92" y="52" width="16" height="16" transform="rotate(45 100 60)" data-base="1"/>
    <rect class="{cls(on3b)}" x="12" y="52" width="16" height="16" transform="rotate(45 20 60)"  data-base="3"/>
    <polygon class="ds-home" points="60,96 68,104 60,112 52,104"/>
  </svg>
</div>
""".strip()


def render_scoreboard(inning: int, topbot: str, my_score: int, opp_score: int) -> str:
    """이닝·스코어를 중계 스코어보드 형태로. 숫자 입력 3개를 대체한다."""
    arrow = "▲" if topbot == "Top" else "▼"
    return f"""
<div class="ds-scoreboard">
  <div class="ds-sb-inning"><span class="ds-sb-arrow">{arrow}</span><span class="ds-sb-num">{inning}</span><span class="ds-sb-unit">회</span></div>
  <div class="ds-sb-score"><span class="ds-sb-num">{my_score}</span><span class="ds-sb-colon">:</span><span class="ds-sb-num">{opp_score}</span></div>
</div>
""".strip()


def render_player_card(name: str, hand: str, subtitle: str, gauges: list[tuple[str, float]]) -> str:
    """선수 카드. raw ID 드롭다운을 대체한다."""
    name_safe = html.escape(name)
    hand_safe = html.escape(hand)
    subtitle_safe = html.escape(subtitle)
    bars = "".join(
        f'<div class="ds-gauge-row"><span class="ds-gauge-label">{html.escape(label)}</span>'
        f'<span class="ds-gauge-track"><span class="ds-gauge-fill"'
        f' style="width:{min(max(value, 0.0), 1.0) * 100:.1f}%"></span></span>'
        f'<span class="ds-gauge-value">{value * 100:.0f}%</span></div>'
        for label, value in gauges
    )
    return f"""
<div class="ds-player-card">
  <div class="ds-player-name">{name_safe}</div>
  <div class="ds-player-meta">{hand_safe} · {subtitle_safe}</div>
  <div class="ds-player-gauges">{bars}</div>
</div>
""".strip()


def clamp_step(step: int, delta: int = 0) -> int:
    """단계를 1~len(STEP_LABELS) 안으로 가둔다.

    범위를 넘으면 예외 대신 끝에서 멈춘다. 첫 단계에서 이전을 눌러도 앱이 죽으면 안 된다.
    """
    return max(1, min(len(STEP_LABELS), step + delta))


def step_visibility(step: int) -> list[bool]:
    """단계별로 어느 블록이 보이는지. 길이는 STEP_LABELS와 같다."""
    current = clamp_step(step)
    return [i + 1 == current for i in range(len(STEP_LABELS))]


def render_step_bar(step: int) -> str:
    """상단 단계 표시. 지난 단계 / 지금 단계 / 남은 단계를 구분해 그린다."""
    current = clamp_step(step)
    dots = []
    for i, label in enumerate(STEP_LABELS, start=1):
        state = "done" if i < current else "now" if i == current else "next"
        dots.append(
            f'<li class="ds-stepdot ds-stepdot--{state}"'
            f' aria-current="{"step" if i == current else "false"}">'
            f'<span class="ds-stepdot__no">{i}</span>'
            f'<span class="ds-stepdot__label">{html.escape(label)}</span></li>'
        )
    return f"""
<nav class="ds-stepbar" aria-label="진행 단계">
  <ol class="ds-stepbar__list">{"".join(dots)}</ol>
</nav>
""".strip()
