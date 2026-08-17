# 덕아웃 콘솔 UI 구현 계획 (트랙 B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4단계 위저드를 한 화면 콘솔로 접고, 폼 컨트롤을 야구 게임 조작으로 바꾸며, 반응형을 실제로 동작시킨다.

**Architecture:** Gradio는 유지한다. `app.py` 2292줄에서 CSS·렌더링을 `ui/` 하위 모듈로 먼저 분리(순수 이동)해 되돌릴 지점을 만든 뒤, 레이아웃을 3열 콘솔로 교체한다. 게임 컨트롤은 `gr.HTML`로 그리고 클릭 이벤트를 숨은 Gradio 컴포넌트에 반영하되, 상태의 단일 진실 공급원은 Gradio state로 유지한다.

**Tech Stack:** Gradio 6.19.0, Python 3.13, HTML/CSS/SVG, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-08-15-accuracy-and-dugout-console-design.md`

## Global Constraints

- **컨펌 게이트 (사용자 지시)**: UI를 `app.py`/`ui/*`에 적용하기 전에 클릭 가능한 목업을 만들어 사용자에게 링크로 보여주고 **명시적 승인을 받는다.** 승인 전에는 Task 4 이후로 진행하지 않는다.
- **색·타이포는 재정의하지 않는다**: 2026-08-04에 확정된 팔레트를 계승한다. 배경 `#f4f2ec`, 카드 `#ffffff`, 보더 `#e6e1d3`, 주 텍스트/네이비 `#14203c`, 주요 액션/레드 `#c8102e`, 안전/그린 `#1f8a4c`, 서브 텍스트 `#6b6555`, 보조 배경 `#f7f5ef`. 폰트는 헤더 `Teko`, 수치 `Share Tech Mono`.
- **버튼은 2종만**: Primary(레드 배경 + 흰 텍스트), Ghost(투명 + 네이비 테두리). 상태색(그린/앰버/레드)은 위험도 표시 전용이며 버튼에 쓰지 않는다.
- **가상환경**: 모든 명령은 `./venv/bin/python`, `./venv/bin/pytest`로 실행한다.
- **앱 포트**: `app.py`는 7862에서 뜬다.
- **백엔드 불변**: `services/*`, `models/*`의 로직을 바꾸지 않는다. 렌더링 함수만 이동한다.
- **터치 타겟**: 모바일 조작 요소는 최소 44x44px.
- **반응형 브레이크포인트**: 데스크톱 ≥1024px(3열), 태블릿 768~1023px(2열), 모바일 <768px(1열 + 존 상단 고정).
- **파일 크기**: 분리 후 `app.py`는 800줄 이하를 목표로 한다. 어떤 파일도 800줄을 넘기지 않는다.

---

### Task 1: CSS 분리 (순수 이동)

**UI를 갈아엎기 전에 되돌릴 지점을 만든다.** 이 태스크는 동작을 1비트도 바꾸지 않는다.

**Files:**
- Create: `ui/styles.py`
- Modify: `app.py` (`CUSTOM_CSS` 제거 + import)

**Interfaces:**
- Consumes: 없음
- Produces: `ui/styles.py::CUSTOM_CSS: str`

- [ ] **Step 1: 이동 전 화면 스냅샷 확보**

```bash
./venv/bin/python app.py &
sleep 25
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```
Expected: `200`

브라우저로 `http://localhost:7862` 접속 → `시작하기` → STEP 1 화면 스크린샷을 `output/screenshots/before-refactor.png`로 저장. 프로세스 종료.

- [ ] **Step 2: `ui/styles.py` 생성**

`app.py:1302`부터 시작하는 `CUSTOM_CSS = """..."""` 블록 전체를 잘라내 `ui/styles.py`로 옮긴다. **문자열 내용을 한 글자도 고치지 않는다.**

```python
# ui/styles.py
"""DiamondScout AI 전역 스타일.

2026-08-04 라이트 브로드캐스트 팔레트를 유지한다.
app.py에서 분리한 이유는 2292줄 모놀리스를 쪼개기 위함이며, 내용 변경은 없다.
"""

CUSTOM_CSS = """
...(app.py에서 그대로 이동)...
"""
```

- [ ] **Step 3: `app.py`에서 import로 교체**

`app.py` 상단 import 구역에 추가한다.

```python
from ui.styles import CUSTOM_CSS
```

`app.py`에 남아 있던 `CUSTOM_CSS = """..."""` 정의를 삭제한다.

- [ ] **Step 4: 동작 동일성 확인**

```bash
./venv/bin/python app.py &
sleep 25
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```
Expected: `200`

브라우저로 접속해 Step 1의 스크린샷과 **육안으로 동일한지** 확인한다. 다르면 이동 중 문자열이 깨진 것이므로 되돌린다. 프로세스 종료.

- [ ] **Step 5: 줄 수 확인**

Run: `wc -l app.py ui/styles.py`
Expected: `app.py`가 약 420줄 줄어들었을 것

- [ ] **Step 6: 커밋**

```bash
git add ui/styles.py app.py
git commit -m "refactor: CUSTOM_CSS를 ui/styles.py로 분리 (순수 이동)

동작 변경 없음. UI 개편 전에 되돌릴 지점을 만들기 위한 사전 분리다."
```

---

### Task 2: 렌더링 함수 분리 (순수 이동)

**Files:**
- Modify: `ui/zone_heatmap.py` (현재 0바이트)
- Modify: `ui/trajectory_view.py` (현재 0바이트)
- Create: `ui/result_panel.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: Task 1
- Produces (모두 **기존 시그니처 그대로**):
  - `ui/zone_heatmap.py`: `_zone_color(norm) -> str`, `_svg_batter_silhouette(cx, ground_y, side) -> str`, `_render_strike_zone_board(...) -> str`, `render_pitcher_zone_board(...) -> str`, `render_batter_zone_board(...) -> str`, `_zone_hand_label(cell, stand) -> str`
  - `ui/trajectory_view.py`: `_trajectory_path(start, end, pitch_label, lateral_sign) -> str`, `_draw_pitch_trajectory(ax, target_x, target_y, color)`, `_draw_ground_background(ax)`, `_draw_batter_silhouette(ax, side, y_center)`, `_draw_ball_marker(ax, cx, cy, glow_color)`, `_draw_home_plate(ax)`, `_draw_mound_marker(ax)`, `_hotcold_grid(zone_scores) -> np.ndarray`, `_render_hotcold_zone(...)`, `render_pitcher_hotcold_zone(...)`, `render_batter_hotcold_zone(...)`
  - `ui/result_panel.py`: `risk_level(key, value) -> tuple[str, str, int]`, `render_risk_cards(risk_summary) -> str`, `_risk_summary_line(label_kr, value, key) -> str`, `render_top3_cards(top3, title) -> str`, `render_hero_recommend_card(...) -> str`, `render_insight_card(title, text) -> str`, `render_analysis_status(done) -> str`

- [ ] **Step 1: 이동 대상 함수 위치 확인**

Run: `grep -n "^def " app.py | head -60`

참고(이동 전 기준 위치): matplotlib 궤적 계열 `app.py:216-465`, SVG 존 보드 계열 `app.py:466-705`, 위험도·카드 렌더러 `app.py:173-215` 및 `app.py:1725-1790`.

- [ ] **Step 2: 함수를 각 모듈로 이동**

각 함수 본문을 **한 글자도 바꾸지 않고** 옮긴다. 모듈 상단에 필요한 import(`numpy as np`, `matplotlib`, 관련 상수)를 추가한다. `risk_level`은 `ui/result_panel.py`에 두고 다른 모듈에서 필요하면 import 한다 — 순환 참조가 생기지 않도록 한 방향으로만 의존시킨다.

- [ ] **Step 3: `app.py`에서 import로 교체**

```python
from ui.result_panel import (
    render_analysis_status, render_hero_recommend_card, render_insight_card,
    render_risk_cards, render_top3_cards, risk_level,
)
from ui.trajectory_view import render_batter_hotcold_zone, render_pitcher_hotcold_zone
from ui.zone_heatmap import render_batter_zone_board, render_pitcher_zone_board
```

`app.py`의 원본 정의를 삭제한다. 삭제로 쓰이지 않게 된 import(`matplotlib` 등)도 정리한다 — **내 변경이 만든 orphan만 정리하고 기존 dead code는 건드리지 않는다.**

- [ ] **Step 4: 기존 테스트 통과 확인**

Run: `./venv/bin/pytest tests/ -v`
Expected: 전체 PASS

- [ ] **Step 5: 앱 기동 + 전체 플로우 확인**

```bash
./venv/bin/python app.py &
sleep 25
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```
Expected: `200`

브라우저에서 투수 모드 분석 1회 완주 → 스트라이크존 보드·Top-3 카드·위험도 카드가 **Task 1 스크린샷과 동일하게** 나오는지 확인. 타자 모드도 1회 확인. 프로세스 종료.

- [ ] **Step 6: 줄 수 확인**

Run: `wc -l app.py ui/*.py`
Expected: `app.py` 1200줄 이하, 각 `ui/*.py` 800줄 이하

- [ ] **Step 7: 커밋**

```bash
git add ui/zone_heatmap.py ui/trajectory_view.py ui/result_panel.py app.py
git commit -m "refactor: 렌더링 함수를 ui/ 하위 모듈로 분리 (순수 이동)

존 보드, matplotlib 궤적, 결과 카드 렌더러를 각 모듈로 옮긴다.
함수 시그니처와 동작은 그대로다."
```

---

### Task 3: 클릭 가능한 목업 제작 — **컨펌 게이트**

**이 태스크의 산출물은 코드가 아니라 사용자 승인이다.** 승인 없이 Task 4로 넘어가지 않는다.

**Files:**
- Create: `output/mockups/dugout-console.html`

**Interfaces:**
- Consumes: Global Constraints의 팔레트 값
- Produces: 사용자가 브라우저로 열어볼 수 있는 정적 HTML 목업 + Artifact 링크

- [ ] **Step 1: 목업 HTML 작성**

`output/mockups/dugout-console.html` 한 파일에 CSS·SVG·JS를 인라인으로 담는다. 데이터는 하드코딩한다 (투수 `Rodón, Carlos` / 타자 임의 이름, Top-3 = 포심 31.7% / 슬라이더 26.8% / 커브 13.1%, 위험도 4종 모두 낮음).

담아야 할 것:

1. **3열 레이아웃** — 좌 매치업 카드 / 중 스트라이크존 + 조작부 / 우 결과 패널
2. **실제 동작하는 게임 컨트롤** (JS로 토글되어야 함)
   - 볼: 불 4개 (`● ● ○ ○`) 클릭 토글
   - 스트라이크: 불 3개
   - 아웃: 불 3개
   - 주자: 다이아몬드 SVG, 1·2·3루 클릭 시 점등
   - 이닝: `[−] 1회 [+]` 스테퍼 + 초/말 토글
   - 스코어: `[−] 0 : 0 [+]`
3. **선수 카드** — 이름 + 좌/우 + 구종 게이지 바 (raw ID 노출 금지)
4. **스트라이크존 3x3 SVG** — 추천 셀 레드 하이라이트 + 궤적 곡선
5. **결과 패널** — Top-3 가로 게이지, 위험도 4종 가로 배지 1줄, 피해야 할 구종 1줄
6. **반응형** — `@media`로 1024/768 브레이크포인트 실제 동작
7. **접힌 섹션** — 코칭 리포트 / Q&A는 `<details>`로 기본 접힘

**링크 보내기 전 자체 점검:**
- [ ] 창 폭을 1440 → 1024 → 768 → 375로 줄여가며 가로 스크롤이 생기지 않는지
- [ ] 모든 클릭 컨트롤이 실제로 반응하는지
- [ ] 팔레트가 Global Constraints의 값과 일치하는지
- [ ] 버튼이 Primary/Ghost 2종만 쓰는지

- [ ] **Step 2: 로컬에서 목업 확인**

Run: `open output/mockups/dugout-console.html`

위 자체 점검 항목을 직접 확인한다.

- [ ] **Step 3: Artifact로 게시**

`artifact-design` 스킬을 먼저 로드한 뒤 Artifact 도구로 `output/mockups/dugout-console.html`을 게시한다. favicon은 야구 이모지로 고정하고, 재게시 시에도 바꾸지 않는다.

- [ ] **Step 4: 사용자에게 링크 전달 + 승인 요청**

전달 시 함께 알릴 것:
- 링크
- 기존 4단계 → 한 화면으로 접었다는 점
- 폼 컨트롤 → 게임 조작으로 바꾼 목록
- 데스크톱/모바일 양쪽에서 봐달라는 요청
- 데이터는 하드코딩된 예시라는 점

- [ ] **Step 5: 승인 대기 — 게이트**

| 사용자 반응 | 조치 |
|---|---|
| 승인 | Task 4로 진행 |
| 수정 요청 | 목업을 고쳐 **같은 file_path로 재게시**(URL 유지) 후 다시 Step 4 |
| 방향 자체를 바꾸자 | 스펙 B절로 돌아가 재설계. 계획을 갱신한 뒤 다시 목업 |

**승인 전에는 `app.py`와 `ui/*`에 UI 변경을 적용하지 않는다.**

- [ ] **Step 6: 커밋**

```bash
git add output/mockups/dugout-console.html
git commit -m "design: 덕아웃 콘솔 UI 목업 추가

한 화면 3열 콘솔 + 게임 조작 컨트롤. 사용자 컨펌용 정적 목업이다."
```

---

### Task 4: 게임 컨트롤 렌더러 + 상태 규약

**전제: Task 3의 사용자 승인 완료.**

**Files:**
- Create: `ui/console.py`
- Create: `tests/test_console_state.py`

**Interfaces:**
- Consumes: Task 3에서 승인된 목업의 마크업·CSS 클래스명
- Produces:
  - `MAX_BALLS = 3`, `MAX_STRIKES = 2`, `MAX_OUTS = 2`
  - `cycle_value(current: int, maximum: int) -> int`
  - `toggle_base(bases: tuple[int, int, int], index: int) -> tuple[int, int, int]`
  - `render_count_lamps(balls: int, strikes: int, outs: int) -> str`
  - `render_base_diamond(on1b: int, on2b: int, on3b: int) -> str`
  - `render_scoreboard(inning: int, topbot: str, my_score: int, opp_score: int) -> str`
  - `render_player_card(name: str, hand: str, subtitle: str, gauges: list[tuple[str, float]]) -> str`

**상태 규약**: HTML은 **표시 전용**이다. 값의 단일 진실 공급원은 Gradio state이며, 클릭 이벤트가 state를 바꾸고 state가 HTML을 다시 그린다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_console_state.py
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
    assert html.count("ds-lamp--off") == 5     # 볼 2 + 스트라이크 1 + 아웃 3 -> 2+1+... 실제값은 구현 후 확정


def test_base_diamond_marks_occupied_bases():
    html = render_base_diamond(on1b=1, on2b=0, on3b=1)

    assert html.count("ds-base--occupied") == 2


def test_renderers_return_html_string():
    assert render_count_lamps(0, 0, 0).lstrip().startswith("<")
    assert render_base_diamond(0, 0, 0).lstrip().startswith("<")
```

**주의**: `test_count_lamps_marks_filled_and_empty`의 off 개수는 램프 총 개수(볼 4 + 스트라이크 3 + 아웃 3 = 10)에서 on 개수(3)를 뺀 **7**이다. 테스트를 쓸 때 이 값으로 확정한다.

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_console_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.console'`

- [ ] **Step 3: 최소 구현 작성**

```python
# ui/console.py
"""덕아웃 콘솔 게임 컨트롤 렌더러.

HTML은 표시 전용이다. 값의 단일 진실 공급원은 Gradio state이며,
클릭 이벤트가 state를 바꾸고 state가 여기 함수들을 다시 호출해 HTML을 갱신한다.
"""

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
    bars = "".join(
        f'<div class="ds-gauge-row"><span class="ds-gauge-label">{label}</span>'
        f'<span class="ds-gauge-track"><span class="ds-gauge-fill"'
        f' style="width:{min(max(value, 0.0), 1.0) * 100:.1f}%"></span></span>'
        f'<span class="ds-gauge-value">{value * 100:.0f}%</span></div>'
        for label, value in gauges
    )
    return f"""
<div class="ds-player-card">
  <div class="ds-player-name">{name}</div>
  <div class="ds-player-meta">{hand} · {subtitle}</div>
  <div class="ds-player-gauges">{bars}</div>
</div>
""".strip()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_console_state.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add ui/console.py tests/test_console_state.py
git commit -m "feat: 덕아웃 콘솔 게임 컨트롤 렌더러 추가

볼카운트 불, 주자 다이아몬드, 스코어보드, 선수 카드.
슬라이더·체크박스·숫자입력·raw ID 드롭다운을 대체한다.
최대치에서 한 번 더 누르면 0으로 돌아가 잘못 눌러도 되돌릴 수 있다."
```

---

### Task 5: 3열 콘솔 레이아웃 적용

**Files:**
- Modify: `app.py` (위저드 제거 + 3열 레이아웃)
- Modify: `ui/styles.py` (콘솔 CSS 추가)

**Interfaces:**
- Consumes: Task 4의 `ui/console.py`
- Produces: 한 화면 콘솔 UI

**제거 대상 (위저드 잔재)**: `WIZARD_STEP_LABELS`, `_step_dot_classes`, `_step_dot_updates`, `_analyze_btn_update`, `_goto_step_1`, `_chip_goto`, 그리고 이들만 쓰던 `gr.Tabs`/스텝 `gr.State` 배선.

- [ ] **Step 1: 위저드 관련 함수·상태 제거**

`app.py`에서 위 목록을 삭제하고, 삭제로 orphan이 된 import·상수를 함께 정리한다. **기존 dead code는 건드리지 않는다.**

- [ ] **Step 2: 3열 레이아웃 구성**

```python
with gr.Row(elem_classes="ds-console"):
    with gr.Column(scale=3, elem_classes="ds-col-matchup"):
        matchup_html = gr.HTML()
    with gr.Column(scale=5, elem_classes="ds-col-zone"):
        zone_html = gr.HTML()
        count_html = gr.HTML()
        diamond_html = gr.HTML()
        scoreboard_html = gr.HTML()
    with gr.Column(scale=4, elem_classes="ds-col-result"):
        result_html = gr.HTML()
```

접히는 섹션은 아래에 둔다.

```python
with gr.Accordion("코칭 리포트", open=False, elem_classes="ds-report-accordion"):
    report_md = gr.Markdown()
with gr.Accordion("Instant Scout Q&A", open=False):
    ...  # 기존 Q&A 컴포넌트를 그대로 옮긴다
```

- [ ] **Step 3: 콘솔 CSS를 `ui/styles.py`에 추가**

Task 3에서 승인된 목업의 CSS를 가져온다. **기존 팔레트 변수만 재사용하고 새 색을 도입하지 않는다.**

```css
/* ===== 덕아웃 콘솔 레이아웃 ===== */
.ds-console { display: grid; grid-template-columns: 3fr 5fr 4fr; gap: 20px; align-items: start; }

@media (max-width: 1023px) {
    .ds-console { grid-template-columns: 1fr 1fr; }
    .ds-col-result { grid-column: 1 / -1; }
}
@media (max-width: 767px) {
    .ds-console { grid-template-columns: 1fr; }
    .ds-col-zone { position: sticky; top: 0; z-index: 5; background: #f4f2ec; }
}

/* 볼카운트 불 */
.ds-lamp { display: inline-block; width: 18px; height: 18px; border-radius: 50%;
           border: 2px solid #14203c; margin-right: 6px; cursor: pointer; }
.ds-lamp--on  { background: #c8102e; border-color: #c8102e; }
.ds-lamp--off { background: transparent; }

/* 주자 다이아몬드 */
.ds-base { fill: #ffffff; stroke: #14203c; stroke-width: 2; cursor: pointer; }
.ds-base--occupied { fill: #c8102e; stroke: #c8102e; }
.ds-home { fill: #14203c; }

/* 모바일 터치 타겟 44px 확보 */
@media (max-width: 767px) {
    .ds-lamp { width: 28px; height: 28px; margin-right: 10px; }
    .ds-lamp-group { min-height: 44px; display: flex; align-items: center; }
}
```

- [ ] **Step 4: 클릭 이벤트 배선**

숨은 `gr.Number`/`gr.State`를 두고 `HTML 클릭 → state 갱신 → HTML 재렌더` 경로를 만든다.

Gradio 6의 `gr.HTML`이 클릭 이벤트를 직접 노출하지 않으면 두 방식 중 하나를 쓴다.
1. 각 컨트롤 위치에 투명한 `gr.Button`을 겹쳐 배치
2. `_js=`로 숨은 컴포넌트 값을 갱신

**어느 방식을 택하든 state가 진실 공급원이라는 규약을 지키고, 확정한 방식을 이 계획서에 기록한다.**

- [ ] **Step 5: 앱 기동 + 동작 확인**

```bash
./venv/bin/python app.py &
sleep 25
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```
Expected: `200`

확인 항목:
- [ ] 한 화면에 매치업·존·결과가 모두 보인다
- [ ] 볼/스트라이크/아웃 불이 클릭에 반응한다
- [ ] 주자 다이아몬드가 클릭에 반응한다
- [ ] 이닝·스코어 스테퍼가 동작한다
- [ ] 입력을 바꾸면 결과가 갱신된다
- [ ] 투수 모드 / 타자 모드 전환이 동작한다

- [ ] **Step 6: 커밋**

```bash
git add app.py ui/styles.py
git commit -m "feat: 4단계 위저드를 한 화면 3열 콘솔로 교체

STEP 1이 드롭다운 2개로 뷰포트를 통째로 쓰던 구조를 없앤다.
스트라이크존이 화면 주인공이 되고, 입력을 바꾸면 결과가 그 자리에서 갱신된다."
```

---

### Task 5Z: 캔버스 스트라이크 존 이식 (계획 보강분)

**왜 뒤늦게 추가되는가**: Task 5를 끝내고 나서야 발견했다. 승인된 목업의 주인공인 캔버스
스트라이크 존(투수/타자 2시점, 실사 배경, 공 회전·궤적)이 원래 계획서 T4~T7 어디에도 없었다.
앱은 여전히 `ui/zone_heatmap.py`의 SVG 보드를 쓴다. T6(선수 카드·결과 패널)·T7(반응형)로는
닫히지 않는다. **T6보다 먼저 한다** — 존이 콘솔의 중심이고 T6의 카드·패널은 그 주변부라,
존 크기가 확정돼야 나머지 레이아웃이 정해진다.

**전제: Task 5 완료(3열 콘솔 레이아웃 적용).**

**Files:**
- Create: `ui/scene.py`
- Create: `ui/static/scene.js`
- Create: `tests/test_scene_payload.py`
- Move: `output/mockups/assets/cut-*.png` → `ui/static/assets/` (git mv)
- Move: `output/mockups/assets/bg-batter-view.jpeg` → `ui/static/assets/` (git mv)
- Modify: `app.py`, `ui/styles.py`

목업 HTML은 이미지 4장을 base64로 **인라인**하고 있어 PNG 파일에 런타임 의존하지 않는다.
따라서 복사가 아니라 이동이며 중복 비용이 0이다.

**통합 방식** (Gradio 6.19 문서 확인 완료):

| 조각 | 수단 | 근거 |
|---|---|---|
| 엔진 정의 | `gr.Blocks(head=f"<script>{scene_engine_js()}</script>")` | `head=`는 페이지 로드 시 1회만 주입된다. `gr.HTML` 안의 `<script>`는 innerHTML 경로라 실행이 보장되지 않는다 |
| 캔버스 마크업 | 정적 `gr.HTML(render_scene_canvas())` | 값이 안 바뀌므로 재렌더 불필요 |
| 데이터 전달 | 숨긴 `gr.Textbox`(JSON) + `.change(None, box, None, js="(v)=>window.dsScene.update(JSON.parse(v))")` | Python이 진실 공급원, JS는 표시 전용. Task 4의 상태 규약과 같다 |
| 이미지 | `gr.set_static_paths([Path("ui/static/assets")])` + `<img src="/gradio_api/file=ui/static/assets/...">` | base64 인라인(1MB)을 매 페이지 로드마다 실어 나르지 않는다 |

**Interfaces:**
- Consumes (전부 기존 코드에 존재): `zone_hit_risk_scores` / `zone_probability_scores`
  (`dict[int, float]`, 키 0~9), `best_cell` / `target_cell` (`int`), `stand` (`"L"`/`"R"`),
  `trajectories` (`list[dict]`: `pitch_label` / `cell` / `rank`)
- Produces:
  - `to_scene_index(cell: int, stand: str) -> int`
  - `build_scene_payload(...) -> dict`
  - `render_scene_canvas() -> str`
  - `scene_engine_js() -> str`
  - JS: `window.dsScene.update(payload)`, `window.dsScene.selfCheck()`

**최대 위험 — 좌표 규약이 양쪽 다 다르다. 이게 이 태스크의 핵심이다.**

| | 앱 (`services/scouting_service.py:18-19`) | 목업 (`dugout-console.html:2034,2048`) |
|---|---|---|
| 인덱스 | `cell` 1~9 | `idx` 0~8 |
| row 0 | **하단**(낮은 코스) — `zone_heatmap.py:78`의 `(2 - row)` 반전이 근거 | **상단**(높은 코스) — `yT = SZ_TOP - (SZ_TOP-SZ_BOT)*(row/3)` |
| col | 투수 시점 **화면** 좌→우 | **타자 기준** 0=바깥쪽·2=몸쪽. 화면 위치는 `insideSign()`이 좌/우타에 따라 자동 반전 |

따라서 **행은 항상 반전, 열은 우타일 때만 반전**이다. 열 규칙의 근거는
`ui/zone_heatmap.py:222-230`의 `_zone_hand_label` — 우타는 col 0이 몸쪽, 좌타는 col 0이 바깥쪽.

이 변환을 엔진 안에 묻으면 TS-007과 똑같이 조용히 틀린다(앱은 뜨고 화면도 그려지는데 값만
뒤집혀 있다). **순수 함수로 떼어내 Python에서 테스트한다.**

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_scene_payload.py`

  최소 다음을 단언한다.
  - `to_scene_index(1, "L") == 6` — cell 1은 app row0(하단)·col0. 좌타면 col0=바깥쪽 → 목업의 낮은 바깥쪽 = idx 6
  - `to_scene_index(1, "R") == 8` — 우타면 col0=몸쪽 → 낮은 몸쪽 = idx 8
  - `to_scene_index(5, "L") == to_scene_index(5, "R") == 4` — 한가운데는 좌/우타 불변
  - `to_scene_index(9, "L") == 2` / `to_scene_index(9, "R") == 0`
  - `{to_scene_index(c, s) for c in range(1, 10)} == set(range(9))` — 좌/우타 각각 전단사
  - `build_scene_payload`가 존 밖 점수(키 0)를 9칸에 섞지 않는다
  - 좌/우타 페이로드가 열 기준 정확한 거울상이다

  검증: `venv/bin/python -m pytest tests/test_scene_payload.py` → **RED**

- [ ] **Step 2: `ui/scene.py` 구현** — Step 1이 GREEN이 될 때까지.

  검증: `venv/bin/python -m pytest tests/` → 기존 23개 포함 전부 통과

- [ ] **Step 3: 엔진을 `ui/static/scene.js`로 추출**

  목업 HTML의 씬 엔진 구간(약 1899~2700행: `ASSETS`/`MODES`/카메라 상수 ~ `renderScene`)을
  **Task 1·2와 같은 순수 이동 규율로** 옮긴다. 손대는 곳은 두 군데뿐이다.
  - 목업 전용 가짜 데이터(`HEAT`, `SCEN`, `QA`)를 제거하고 `window.dsScene.update(payload)`가
    채우는 모듈 변수로 바꾼다
  - base64 `data:` URL을 `/gradio_api/file=ui/static/assets/...` 경로로 바꾼다

  카메라 상수(`F`, `cyRatio`, `panMag`, `Xmag`, `hpx`)는 **v4 확정값 그대로** 옮긴다. v5(존 확대)는
  사용자가 이미 철회했다(progress.md 참조). 주석에 남은 v5 값도 함께 옮겨 다음 사람이 같은
  방향으로 되돌아가지 않게 한다.

  검증: `node --check ui/static/scene.js` PASS, 외부 참조 0건, `output/mockups/`의 원본과
  diff를 떠서 변경분이 위 두 항목뿐임을 확인

- [ ] **Step 4: `app.py` 배선**

  `render_pitcher_zone_board` / `render_batter_zone_board` 호출부 2곳(`app.py:581`, `app.py:661`)을
  `build_scene_payload` + 숨긴 JSON 박스 갱신으로 교체한다.

  **잔존 참조 grep을 완료 조건에 넣는다** (Task 5 룰링). `render_pitcher_zone_board` /
  `render_batter_zone_board` / `_render_strike_zone_board` / `zone_html`을 grep해 0건이거나,
  남아 있다면 의도적으로 남긴 것임을 근거와 함께 적는다.

  `ui/zone_heatmap.py`는 **이번 태스크에서 삭제하지 않는다** — `_zone_hand_label`이 살아 있고
  `ZONE_COL_OF_CELL` 해석의 근거 문서 역할을 한다. 사용 여부는 T7에서 판정한다.

- [ ] **Step 5: 실제 앱 검증 (필수 — 테스트로 대체 불가)**

  TS-007이 바이트 동일성·코드 리뷰·테스트 23개를 전부 통과하고도 버튼 한 번에 터졌다.
  캔버스는 Python 테스트가 닿지 않는 영역이라 이 단계가 유일한 안전망이다.
  - `venv/bin/python app.py` → HTTP 200
  - 브라우저에서 **분석을 실제로 실행**하고 캔버스가 그려지는지 확인
  - 투수/타자 두 시점 전환
  - 좌타/우타 전환 시 존·라벨·인물이 전부 동시에 거울상이 되는지
  - 9칸 점수가 SVG 보드(교체 전)와 같은 값을 같은 자리에 표시하는지 — **좌표 매핑의 최종 검증**
  - 공 궤적 애니메이션 재생, 콘솔 에러 0건(Gradio 자체 CDN preload 실패는 기존 알려진 잡음)

**완료 조건**: 위 Step 1~5 전부 + `ui/static/scene.js` 800줄 이하.

---

### Task 6: 선수 카드 + 결과 패널 재구성

**Files:**
- Modify: `app.py`
- Modify: `ui/result_panel.py`
- Modify: `ui/styles.py`
- Create: `tests/test_result_panel.py`

**Interfaces:**
- Consumes: Task 4의 `render_player_card`, Task 2의 `risk_level`
- Produces:
  - `ui/result_panel.py::RISK_LABELS_KR: dict[str, str]`
  - `ui/result_panel.py::render_risk_badges(risk_summary: dict) -> str` — 세로 카드 4개를 대체하는 가로 1줄 배지
  - `ui/result_panel.py::render_top3_gauges(top3: list[dict]) -> str` — 존 옆 가로 게이지

**트랙 A 의존**: 타자 이름 표시는 트랙 A Task 1의 `player_names.csv`에 의존한다. 아직 없으면 `Batter ID {id}` 폴백으로 동작하되 **레이아웃은 이름이 들어올 자리를 확보해둔다.**

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_result_panel.py
from ui.result_panel import render_risk_badges, render_top3_gauges


def test_risk_badges_render_all_four_in_one_row():
    summary = {"pattern": 0.319, "extra_base": 0.042, "home_run": 0.017, "walk": 0.104}

    html = render_risk_badges(summary)

    assert html.count("ds-risk-badge") == 4
    assert "ds-risk-row" in html


def test_risk_badges_handle_missing_value():
    """값이 없는 위험도도 예외 없이 렌더되어야 한다."""
    html = render_risk_badges({"pattern": 0.3})

    assert html.count("ds-risk-badge") == 4


def test_top3_gauges_render_three_bars_in_order():
    top3 = [
        {"label_kr": "포심 패스트볼", "label": "FF", "prob": 0.317},
        {"label_kr": "슬라이더", "label": "SL", "prob": 0.268},
        {"label_kr": "커브", "label": "CU", "prob": 0.131},
    ]

    html = render_top3_gauges(top3)

    assert html.count("ds-gauge-fill") == 3
    assert html.index("포심") < html.index("슬라이더") < html.index("커브")


def test_top3_gauge_shows_probability_as_percent():
    top3 = [{"label_kr": "포심 패스트볼", "label": "FF", "prob": 0.317}]

    assert "31.7%" in render_top3_gauges(top3)


def test_top3_first_rank_gets_emphasis_class():
    top3 = [
        {"label_kr": "포심 패스트볼", "label": "FF", "prob": 0.317},
        {"label_kr": "슬라이더", "label": "SL", "prob": 0.268},
    ]

    assert render_top3_gauges(top3).count("ds-gauge-row--top") == 1
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_result_panel.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_risk_badges'`

- [ ] **Step 3: 최소 구현 작성**

`ui/result_panel.py`에 추가한다. Task 2에서 이동해온 `risk_level(key, value) -> (라벨, 색, 퍼센트)`를 재사용한다.

```python
RISK_LABELS_KR = {
    "pattern": "패턴 노출",
    "extra_base": "장타",
    "home_run": "홈런",
    "walk": "볼넷",
}


def render_risk_badges(risk_summary: dict) -> str:
    """위험도 4종을 가로 1줄 배지로. 기존 세로 카드 4개를 대체한다."""
    badges = []
    for key, label_kr in RISK_LABELS_KR.items():
        level, color, pct = risk_level(key, risk_summary.get(key))
        badges.append(
            f'<div class="ds-risk-badge">'
            f'<span class="ds-risk-dot" style="background:{color}"></span>'
            f'<span class="ds-risk-label">{label_kr}</span>'
            f'<span class="ds-risk-level" style="color:{color}">{level}</span>'
            f'<span class="ds-risk-pct">{pct}%</span>'
            f"</div>"
        )
    return f'<div class="ds-risk-row">{"".join(badges)}</div>'


def render_top3_gauges(top3: list[dict]) -> str:
    """Top-3를 존 옆 가로 게이지로. 1위는 레드로 강조한다."""
    rows = []
    for rank, item in enumerate(top3, start=1):
        pct = item["prob"] * 100
        emphasis = " ds-gauge-row--top" if rank == 1 else ""
        rows.append(
            f'<div class="ds-gauge-row{emphasis}">'
            f'<span class="ds-gauge-rank">{rank}</span>'
            f'<span class="ds-gauge-label">{item["label_kr"]} ({item["label"]})</span>'
            f'<span class="ds-gauge-track">'
            f'<span class="ds-gauge-fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="ds-gauge-value">{pct:.1f}%</span>'
            f"</div>"
        )
    return f'<div class="ds-top3-gauges">{"".join(rows)}</div>'
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_result_panel.py -v`
Expected: PASS (5 passed)

`test_risk_badges_handle_missing_value`가 실패하면 `risk_level`이 `None`을 처리하지 못하는 것이다. `risk_level`의 기존 동작을 확인하고, 처리하지 못하면 **호출부에서** `None` 케이스를 막는다 — 이동해온 함수 자체를 고치지 않는다.

- [ ] **Step 5: 선수 카드를 실제 데이터에 연결**

`app.py`의 드롭다운 라벨 생성부를 `render_player_card` 사용으로 바꾼다. 타자 이름은 `data/processed/batter_matchup_profile_2025.csv`의 `player_name`(트랙 A Task 1에서 추가)을 읽고, 컬럼이 없으면 `Batter ID {id}`로 degrade 한다. 게이지는 구종별 `whiff_rate` 상위 2개를 쓴다.

- [ ] **Step 6: 앱 기동 + 확인**

```bash
./venv/bin/python app.py &
sleep 25
```
확인:
- [ ] 타자가 raw ID가 아니라 이름으로 표시된다 (또는 폴백이 자연스럽다)
- [ ] Top-3가 존 옆 가로 게이지로 나온다
- [ ] 위험도가 가로 1줄이다
- [ ] 결과 화면 스크롤 길이가 개편 전보다 짧다

- [ ] **Step 7: 커밋**

```bash
git add ui/result_panel.py tests/test_result_panel.py app.py ui/styles.py
git commit -m "feat: 선수 카드 + 결과 패널 재구성

세로로 늘어지던 결과 카드를 존 옆 게이지와 가로 배지로 접는다.
선수를 raw ID 대신 이름·손잡이·구종 게이지 카드로 표시한다."
```

---

### Task 7: 반응형 검증 + 마무리

**Files:**
- Modify: `ui/styles.py` (검증 중 발견한 문제 수정)
- Modify: `README.md` (스크린샷·설명 갱신)

- [ ] **Step 1: 4개 폭에서 검증**

앱을 띄우고 브라우저 창을 각 폭으로 맞춰 확인한다.

| 폭 | 확인 항목 |
|---|---|
| 1440 | 3열 배치, 가로 스크롤 없음, 우측 여백이 과하지 않음 |
| 1024 | 3열 유지 또는 2열 전환, 존 크기 유지 |
| 768 | 2열 → 1열 전환, 존 상단 sticky 동작 |
| 375 | 조작부 터치 타겟 44px 이상, 가로 스크롤 없음, 글자 잘림 없음 |

각 폭 스크린샷을 `output/screenshots/responsive-{width}.png`로 저장한다.

- [ ] **Step 2: 발견한 문제 수정**

`ui/styles.py`의 미디어 쿼리를 고친다. 새 색을 도입하지 않고 기존 팔레트 안에서 해결한다.

- [ ] **Step 3: 전체 회귀 확인**

Run: `./venv/bin/pytest tests/ -v`
Expected: 전체 PASS

앱에서 확인:
- [ ] 투수 모드 분석 완주
- [ ] 타자 모드 분석 완주
- [ ] 타석 시뮬레이터 동작
- [ ] Instant Scout Q&A 응답
- [ ] PDF 리포트 생성

- [ ] **Step 4: 파일 크기 확인**

Run: `wc -l app.py ui/*.py`
Expected: `app.py` 800줄 이하, 모든 `ui/*.py` 800줄 이하

초과하면 해당 파일을 책임 단위로 더 쪼갠다.

- [ ] **Step 5: README 스크린샷·데모 GIF 갱신**

새 UI로 `output/screenshots/`의 이미지와 `pitcher-mode-demo.gif`를 다시 찍는다. README의 "4단계 위저드(매치업 → 상황판 → 베이스&스코어 → 작전지시)" 설명 문장을 한 화면 콘솔 설명으로 고친다.

- [ ] **Step 6: 커밋**

```bash
git add ui/styles.py README.md output/screenshots/
git commit -m "fix: 반응형 검증 후 브레이크포인트 보정 + README 갱신

1440/1024/768/375 4개 폭에서 가로 스크롤·터치 타겟을 확인했다."
```

---

## 자체 검토 결과

**스펙 커버리지**

| 스펙 항목 | 태스크 |
|---|---|
| B-1 위저드 → 한 화면 콘솔 | Task 5 |
| B-2 3열 레이아웃 + 반응형 | Task 5, Task 7 |
| B-3 게임 조작 컨트롤 | Task 4, Task 5 |
| B-4 선수 카드 (이름 포함) | Task 6 (데이터는 트랙 A Task 1 의존) |
| B-5 결과 표현 재구성 | Task 6 |
| B-6 `ui/` 파일 분리 | Task 1, Task 2 |
| B-7 반응형 검증 기준 | Task 7 |
| UI 컨펌 게이트 | Task 3 |

누락 없음.

**타입 일관성 확인**

- `render_count_lamps(balls, strikes, outs)` 시그니처가 Task 4 정의와 테스트에서 일치
- `toggle_base(bases, index)`가 튜플을 받아 새 튜플을 반환 — 불변 패턴을 테스트로 강제
- `risk_level(key, value) -> (라벨, 색, 퍼센트)`는 기존 `app.py:173` 함수를 Task 2에서 이동한 것이며 Task 6에서 재사용. 시그니처 변경 없음
- CSS 클래스명이 Python 렌더러(`ds-lamp--on`, `ds-lamp--off`, `ds-base--occupied`, `ds-gauge-fill`, `ds-gauge-row--top`, `ds-risk-badge`, `ds-risk-row`)와 `ui/styles.py`, 테스트 assertion 3곳에서 모두 일치

**트랙 A와의 의존 관계**

- Task 6의 타자 이름 표시만 트랙 A Task 1(`player_names.csv`)에 의존한다. 트랙 A가 먼저 끝나 있으면 이름이 나오고, 아니면 `Batter ID {id}` 폴백으로 동작한다 — **어느 순서로 진행해도 깨지지 않는다.**
- 그 외에는 두 트랙이 독립이다. `services/prediction_service.py`의 반환 형식이 트랙 A Task 10에서도 불변으로 유지되므로 UI가 영향받지 않는다.

**남은 가정**

- Gradio 6.19.0의 `gr.HTML`이 클릭 이벤트를 직접 노출하지 않는다고 가정한다. Task 5 Step 4에서 실제 API를 확인해 투명 버튼 오버레이 / `_js=` 중 동작하는 쪽을 택하고, 확정 방식을 이 계획서에 기록한다.
- Task 3의 목업 승인이 한 번에 나지 않을 수 있다. 수정 반복은 정상 경로이며 Task 4 이후 일정에 영향을 준다.
- Task 2의 함수 이동 시 `app.py`의 현재 줄 번호는 Task 1 수행 후 약 420줄 앞당겨진다. `grep -n "^def "`로 매번 실제 위치를 확인한다.
