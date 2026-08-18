"""덕아웃 콘솔 게임 컨트롤 렌더러.

HTML은 표시 전용이다. 값의 단일 진실 공급원은 Gradio state이며,
클릭 이벤트가 state를 바꾸고 state가 여기 함수들을 다시 호출해 HTML을 갱신한다.
"""

import html

MAX_BALLS = 3
MAX_STRIKES = 2
MAX_OUTS = 2


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
