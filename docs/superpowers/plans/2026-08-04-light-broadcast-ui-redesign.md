# 라이트 스포츠 브로드캐스트 UI 리디자인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DiamondScout AI의 Gradio UI를 다크 네온 "야간경기 스타디움" 톤에서 "라이트 스포츠 브로드캐스트"(크림 배경 + 네이비 + 레드 포인트) 톤으로 전면 재도장하고, CTA 버튼 색상을 통일하고, 결과 화면을 벤토 그리드로 재구성하고, 데스크톱 1280px+ 에서 2단(위저드+매치업 요약 패널) 반응형 레이아웃을 적용한다.

**Architecture:** 변경은 전부 `app.py` 한 파일 안에서 이뤄진다. `CUSTOM_CSS` 문자열 상수를 새 팔레트로 전면 교체하고, SVG를 직접 그리는 STRIKE ZONE BOARD 함수의 하드코딩된 색상을 라이트 카드에 맞게 보정하고, 결과 카드 HTML을 생성하는 몇 개 함수의 인라인 색상을 바꾸고, 위저드 스텝 버튼에 상태별 CSS 클래스를 동적으로 부여하고, 새 "매치업 요약" 패널 컴포넌트를 추가한다. 위저드 4단계 순서·`gr.State` 기반 전환 메커니즘·`services/*`/`models/*` 백엔드 로직은 건드리지 않는다.

**Tech Stack:** Python, Gradio 6, 순수 CSS (미디어 쿼리 기반 반응형). 자동화된 UI 테스트 프레임워크가 이 프로젝트에 없으므로(`CLAUDE.md`에 `tests/ ★ 현재 없음. 신규` 로 명시), 각 태스크의 "테스트"는 앱을 재기동해 브라우저로 직접 확인하는 수동 시각 검증으로 대체한다. TDD RED/GREEN 대신 "재기동 → 스크린샷 → 스펙과 대조"를 검증 루프로 쓴다.

## Global Constraints

- 대상 파일: `app.py` 만 수정. `services/*`, `models/*` 백엔드 로직 변경 금지.
- 4단계 위저드 순서(매치업→상황판→베이스&스코어→작전지시)와 `gr.State(step_index)` 기반 전환 메커니즘 변경 금지.
- 색상 팔레트 고정값: 배경 `#f4f2ec`, 카드 배경 `#ffffff`, 카드 테두리 `#e6e1d3`, 네이비(주 텍스트) `#14203c`, 레드(주요 액션) `#c8102e`, 그린(안전) `#1f8a4c`.
- 버튼은 Primary(레드 배경)/Ghost(아웃라인) 2종만 사용 — 기존 초록·청록·보라 3색 혼재 금지.
- 반응형 브레이크포인트: 모바일 `<640px`(1열), 태블릿 `640–1279px`(1열, 결과 카드 2열), 데스크톱 `≥1280px`(2단 레이아웃, 결과 카드 4열).
- 투수 모드(`p_` 접두)와 타자 모드(`b_` 접두)는 구조가 완전히 동일하므로 모든 UI 태스크는 두 탭 모두에 적용한다.
- 참고 스펙: `docs/superpowers/specs/2026-08-04-light-broadcast-ui-redesign-design.md`

---

### Task 1: CSS 디자인 토큰 전면 교체 (라이트 테마)

**Files:**
- Modify: `app.py:1295-1469` (`CUSTOM_CSS` 상수 전체)

**Interfaces:**
- Consumes: 없음 (독립적인 CSS 상수 교체)
- Produces: `.ds-panel`, `.ds-board`, `.ds-qa-panel`, `.ds-btn-next`, `.ds-btn-prev`, `.ds-btn-analyze`, `.ds-btn-reset`, `.ds-btn-pdf`, `.ds-zone-card` 등 이후 태스크가 계속 참조하는 클래스 — 이 태스크에서 최종 정의를 확정한다. Task 4가 새로 쓰는 `.ds-step-dot`/`.ds-step-done`/`.ds-step-now`/`.ds-step-next`, Task 5가 쓰는 `.ds-matchup-panel`, Task 6이 쓰는 `.ds-bento`/`.ds-bento-wide` 클래스도 이 태스크에서 함께 정의한다.

- [ ] **Step 1: `CUSTOM_CSS` 전체를 새 라이트 팔레트로 교체**

`app.py`에서 다음 블록(1295번째 줄의 `CUSTOM_CSS = """` 부터 1469번째 줄의 닫는 `"""` 까지)을 통째로 아래 내용으로 교체한다.

```python
CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Teko:wght@500;600;700&family=Share+Tech+Mono&display=swap');

:root {
    color-scheme: light;
}
.gradio-container {
    background: #f4f2ec !important;
    max-width: 1320px !important;
    margin: 0 auto !important;
    font-size: 15.5px !important;
    color-scheme: light;
    /* Gradio 6 내부 컴포넌트(슬라이더/드롭다운 등)가 라이트 팔레트를 그대로 쓰도록
       변수 레벨에서 고정한다. .ds-* 클래스만으로는 내부 컴포넌트가 예전 다크 변수값을
       참조해 라이트/다크가 뒤섞여 보이는 문제가 있었다 (2026-08-03 스펙에서 겪은 문제의
       재발 방지). */
    --body-background-fill: #f4f2ec !important;
    --background-fill-primary: #ffffff !important;
    --background-fill-secondary: #f7f5ef !important;
    --border-color-primary: #e6e1d3 !important;
    --border-color-accent: #c8102e !important;
    --block-background-fill: #ffffff !important;
    --block-border-color: #e6e1d3 !important;
    --block-label-background-fill: #ffffff !important;
    --block-label-text-color: #6b6555 !important;
    --body-text-color: #14203c !important;
    --body-text-color-subdued: #6b6555 !important;
    --input-background-fill: #f7f5ef !important;
    --checkbox-background-color: #f7f5ef !important;
    --checkbox-background-color-selected: #c8102e !important;
    --neutral-950: #14203c !important;
}
.gradio-container, .gradio-container p, .gradio-container span, .gradio-container label {
    color: #14203c;
}
.gradio-container h1, .gradio-container h2, .gradio-container h3, .gradio-container h4,
.gradio-container button, .ds-panel-title, .ds-board-title, .ds-qa-title, .ds-step-dot {
    font-family: 'Teko', 'Pretendard', sans-serif !important;
    letter-spacing: 0.02em;
}
.gradio-container input,
.gradio-container textarea,
.gradio-container select {
    background: #f7f5ef !important;
    color: #14203c !important;
}
.gradio-container h1 { color: #14203c; font-size: 30px !important; margin-bottom: 6px !important; }
.gradio-container h2 { color: #14203c; font-size: 22px !important; }
.gradio-container h3, .gradio-container h4 {
    color: #14203c; font-size: 18px !important; margin-top: 26px !important; margin-bottom: 12px !important;
}
/* 입력 영역 = 경기 설정 패널 / 결과 영역 = 코칭 보드 / Q&A 패널 공통 카드 스타일 */
.ds-panel, .ds-board, .ds-qa-panel {
    border-radius: 16px !important;
    padding: 24px 26px !important;
    margin: 20px 0 !important;
    background: #ffffff !important;
    border: 1px solid #e6e1d3 !important;
    box-shadow: 0 4px 14px rgba(20,32,60,0.06);
}
.ds-panel-title, .ds-board-title, .ds-qa-title {
    font-weight: 800; letter-spacing: 0.03em; font-size: 17px; padding: 2px 0 14px 12px;
    margin: 0 !important; border-left: 4px solid;
}
.ds-panel-title { color: #c8102e; border-color: #c8102e; }
.ds-board-title { color: #14203c; border-color: #14203c; }
.ds-qa-title { color: #14203c; border-color: #c8102e; }
/* 볼/스트라이크/아웃 스코어보드 */
.ds-scoreboard {
    background: #f7f5ef !important;
    border: 1px solid #e6e1d3 !important;
    border-radius: 12px !important;
    padding: 14px 10px !important;
    margin: 6px 0 16px 0 !important;
}
.ds-scoreboard input[type=range] { accent-color: #c8102e; }
.ds-scoreboard input[type=number] { font-family: 'Share Tech Mono', monospace !important; }
/* 주자 베이스 카드 */
.ds-base-card {
    background: #f7f5ef !important; border: 1px solid #e6e1d3 !important; border-radius: 10px !important;
    padding: 4px 2px !important;
}
.ds-base-card label { font-size: 15.5px !important; }
.ds-base-card label::before { content: "\\25C6"; color: #b8ae94; margin-right: 6px; }
.ds-base-card:has(input:checked) { border-color: #c8102e !important; box-shadow: 0 0 0 2px rgba(200,16,46,0.15); }
.ds-base-card:has(input:checked) label::before { color: #c8102e; }
/* 버튼: Primary(레드)/Ghost(아웃라인) 2종만 사용 */
.gradio-container button { font-size: 15.5px !important; border-radius: 8px !important; }
.ds-btn-next, .ds-btn-analyze {
    background: #c8102e !important; color: #ffffff !important; border: none !important;
    font-weight: 800 !important; box-shadow: 0 4px 10px rgba(200,16,46,0.28) !important;
}
.ds-btn-next:hover, .ds-btn-analyze:hover { box-shadow: 0 6px 16px rgba(200,16,46,0.4) !important; transform: translateY(-1px); }
.ds-btn-analyze { font-size: 18px !important; padding: 16px !important; margin-top: 12px !important; }
.ds-btn-prev, .ds-btn-reset {
    background: transparent !important; color: #6b6555 !important; border: 1.5px solid #ddd8ca !important;
    box-shadow: none !important; font-weight: 700 !important;
}
.ds-btn-prev:hover, .ds-btn-reset:hover { border-color: #14203c !important; color: #14203c !important; }
.ds-btn-reset { margin-bottom: 10px !important; }
.ds-btn-pdf {
    background: transparent !important; color: #14203c !important; border: 1.5px solid #14203c !important;
    font-size: 15px !important; padding: 11px !important; font-weight: 700 !important; box-shadow: none !important;
}
.ds-btn-pdf:hover { background: #14203c !important; color: #ffffff !important; }
/* 입력 컴포넌트 라벨/텍스트 가독성 */
.gradio-container label span, .gradio-container .label-wrap span { font-size: 15px !important; }
/* STRIKE ZONE BOARD 카드 (내부 SVG 히트맵 자체 색상은 Task 2에서 별도 보정) */
.ds-zone-card {
    background: #ffffff;
    border: 1px solid #e6e1d3; border-radius: 16px; padding: 18px 20px 14px;
    box-shadow: 0 4px 14px rgba(20,32,60,0.06);
}
.ds-zone-header { text-align: center; letter-spacing: 0.06em; font-weight: 800; }
.ds-zone-header-en { color: #c8102e; font-size: 20px; }
.ds-zone-header-sep { color: #b8ae94; margin: 0 10px; font-weight: 400; }
.ds-zone-header-kr { color: #14203c; font-size: 18px; }
.ds-zone-badge {
    background: rgba(200,16,46,0.08); color: #c8102e; border: 1px solid rgba(200,16,46,0.3);
    border-radius: 999px; font-size: 11px; padding: 3px 10px; margin-left: 10px; letter-spacing: 0.05em;
}
.ds-zone-sub { text-align: center; color: #6b6555; font-size: 13.5px; margin-top: 4px; }
.ds-zone-svg { width: 100%; height: auto; display: block; margin-top: 6px; }
.ds-zone-footer {
    display: flex; align-items: center; justify-content: space-between; color: #6b6555;
    font-size: 13px; margin-top: 4px; gap: 10px;
}
.ds-zone-legend { display: flex; align-items: center; gap: 8px; }
.ds-zone-legend-pill {
    width: 70px; height: 8px; border-radius: 999px;
    background: linear-gradient(90deg, rgb(8,145,178), rgb(225,29,72));
}
.ds-zone-legend-label { font-size: 11px; color: #9a927c; }
.ds-zone-caption { text-align: center; color: #14203c; font-weight: 700; font-size: 15px; margin-top: 10px; }
/* 분석 완료/진행 상태 표시 */
.ds-status {
    text-align: center; font-weight: 700; font-size: 14.5px; padding: 10px 14px;
    border-radius: 10px; margin: 6px 0 14px 0;
}
.ds-status-done { background: rgba(31,138,76,0.08); color: #1f8a4c; border: 1px solid rgba(31,138,76,0.3); }
.ds-status-pending { background: rgba(184,134,11,0.08); color: #8a6d00; border: 1px solid rgba(184,134,11,0.3); }

/* ===== 위저드 카드 ===== */
.ds-wizard-card { position: relative; }
.ds-wizard-card[style*="display: none"] {
    display: none !important; height: 0 !important; min-height: 0 !important;
    padding: 0 !important; margin: 0 !important; border: none !important; overflow: hidden !important;
}
/* 스텝 전환은 위쪽 진행 트랙으로만 하므로 gr.Tabs 기본 헤더는 숨긴다 */
.ds-wizard-tabs > .tab-wrapper { display: none !important; }

/* ===== 위저드 진행 트랙 (완료=레드 밑줄 / 현재=네이비 강조 / 예정=연한 회색) ===== */
.ds-wizard-progress { gap: 4px !important; margin: 4px 0 22px 0 !important; flex-wrap: nowrap !important; }
.ds-step-dot {
    flex: 1; border-radius: 8px 8px 0 0 !important; border: none !important;
    border-bottom: 3px solid #ddd8ca !important; background: transparent !important; box-shadow: none !important;
    color: #b8ae94 !important; font-weight: 700 !important; padding: 10px 6px !important; font-size: 13.5px !important;
}
.ds-step-dot:hover { color: #14203c !important; }
.ds-step-done { border-bottom-color: #c8102e !important; color: #c8102e !important; }
.ds-step-now {
    border-bottom-color: #14203c !important; color: #14203c !important;
    background: #f7f5ef !important; border-radius: 8px 8px 0 0 !important;
}
.ds-step-next { border-bottom-color: #ddd8ca !important; color: #b8ae94 !important; }

/* ===== 현재 매치업 요약 패널 (데스크톱 전용, Task 5) ===== */
.ds-matchup-panel {
    display: none;
    background: #14203c !important; color: #ffffff !important;
    border-radius: 16px !important; padding: 22px !important;
}
.ds-matchup-panel .ds-mp-title {
    font-size: 12px; font-weight: 700; letter-spacing: 0.08em; color: #b9c3dd; text-transform: uppercase;
    border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 10px; margin-bottom: 10px;
}
.ds-matchup-panel .ds-mp-row {
    display: flex; justify-content: space-between; gap: 10px; font-size: 13px; padding: 7px 0;
    border-bottom: 1px dashed rgba(255,255,255,0.12);
}
.ds-matchup-panel .ds-mp-row span:first-child { color: #b9c3dd; }
.ds-matchup-panel .ds-mp-row span:last-child { font-weight: 700; text-align: right; }

/* ===== 결과 화면 벤토 그리드 (Task 6) ===== */
.ds-bento { display: grid !important; grid-template-columns: 1fr 1fr; gap: 14px; margin: 10px 0; }
.ds-bento > .form { background: transparent !important; border: none !important; box-shadow: none !important; }
.ds-bento-wide { grid-column: 1 / -1 !important; }

/* ===== 반응형 브레이크포인트 ===== */
@media (min-width: 1280px) {
    .ds-matchup-panel { display: block; }
    .ds-bento { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 639px) {
    .ds-step-dot { font-size: 11.5px !important; padding: 8px 3px !important; }
    .ds-panel, .ds-board, .ds-qa-panel { padding: 16px 14px !important; }
}
"""
```

- [ ] **Step 2: 앱 재기동 후 기동 확인**

```bash
pkill -f "python -u app.py" || true
cd /Users/tina/Project/DiamondScout_AI && source venv/bin/activate && nohup python app.py > /tmp/diamondscout.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`. `/tmp/diamondscout.log`에 Python 예외(Traceback)가 없는지 확인한다 (CSS 문자열의 중괄호/따옴표 오타는 런타임 에러로 안 뜨고 화면이 깨지는 형태로만 나타나므로, 이 시점에서는 "서버가 죽지 않았는지"만 확인하고 실제 시각 검증은 Task 7에서 한다).

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "style: 라이트 스포츠 브로드캐스트 팔레트로 CUSTOM_CSS 전면 교체"
```

---

### Task 2: STRIKE ZONE BOARD SVG 색상을 라이트 카드에 맞게 보정

**Files:**
- Modify: `app.py:598-630` (`_render_strike_zone_board` 내부 SVG 색상 리터럴)

**Interfaces:**
- Consumes: Task 1에서 정의한 `.ds-zone-card`(흰 배경) — 이 태스크는 그 흰 배경 위에서 SVG 자체가 그리는 도형 색이 보이도록 보정한다.
- Produces: 없음 (순수 시각 보정, 함수 시그니처 변경 없음)

**구현 노트:** 히트맵 셀 자체의 시안→로즈 그라디언트(`_zone_color`)는 위험도를 나타내는 의미 있는 색이므로 그대로 둔다. 셀 위에 얹히는 퍼센트 텍스트(`fill="#f8fafc"` + 어두운 stroke 외곽선)는 항상 색이 있는 셀 위에 그려지므로 카드 배경이 바뀌어도 그대로 잘 보인다 — 이 부분은 건드리지 않는다. 문제는 **카드의 흰 배경 위에 직접 그려지는 요소**(그리드 테두리, 홈플레이트, 궤적선)로, 기존 다크 배경을 전제로 밝은/시안 색을 썼던 부분이다.

- [ ] **Step 1: 궤적선 색상을 라이트 배경에서도 대비되게 변경**

`app.py:566-571`의 다음 블록:

```python
        if rank == 1:
            color, width, opacity, ball_r = "#fde68a", 4.2, 0.85, 7
        elif rank == 2:
            color, width, opacity, ball_r = "#67e8f9", 2.6, 0.35, 5
        else:
            color, width, opacity, ball_r = "#67e8f9", 2.2, 0.22, 4
```

를 다음으로 교체:

```python
        if rank == 1:
            color, width, opacity, ball_r = "#c8102e", 4.2, 0.85, 7
        elif rank == 2:
            color, width, opacity, ball_r = "#14203c", 2.6, 0.30, 5
        else:
            color, width, opacity, ball_r = "#14203c", 2.2, 0.18, 4
```

(기존 시안색은 다크 배경 전제였고 opacity 0.22~0.35의 옅은 시안은 흰 카드 위에서 거의 안 보인다. 1순위=레드, 2·3순위=네이비로 바꿔 대비를 확보한다.)

- [ ] **Step 2: 추천 셀 마커 색상을 그린 계열로 통일**

`app.py:593-597`의 다음 블록:

```python
        if is_best:
            cx_ball, cy_ball = x + CELL / 2, y + CELL / 2
            cells_svg.append(f"""
            <circle cx="{cx_ball}" cy="{cy_ball}" r="30" fill="#fde68a" opacity="0.18" />
            <circle cx="{cx_ball}" cy="{cy_ball}" r="13" fill="#fffbeb" stroke="#4ade80" stroke-width="1.6" />""")
```

를 다음으로 교체:

```python
        if is_best:
            cx_ball, cy_ball = x + CELL / 2, y + CELL / 2
            cells_svg.append(f"""
            <circle cx="{cx_ball}" cy="{cy_ball}" r="30" fill="#1f8a4c" opacity="0.14" />
            <circle cx="{cx_ball}" cy="{cy_ball}" r="13" fill="#ffffff" stroke="#1f8a4c" stroke-width="1.8" />""")
```

그리고 같은 함수 내 `border = "#4ade80" if is_best else "rgba(226,232,240,0.35)"` 줄(`app.py:588`)을 다음으로 교체:

```python
        border = "#1f8a4c" if is_best else "rgba(20,32,60,0.18)"
```

(기존 `rgba(226,232,240,0.35)`는 거의 흰색 반투명이라 흰 카드 위에서 셀 경계가 안 보인다. 네이비 계열 저채도로 바꿔 셀 구분선을 확보한다.)

- [ ] **Step 3: 그리드 테두리 색상 변경**

`app.py:658-659`의 다음 블록:

```python
        <rect x="{GRID_LEFT}" y="{GRID_TOP}" width="{3*CELL}" height="{3*CELL}" rx="16" fill="none"
              stroke="#e2e8f0" stroke-width="2.2" />
```

를 다음으로 교체:

```python
        <rect x="{GRID_LEFT}" y="{GRID_TOP}" width="{3*CELL}" height="{3*CELL}" rx="16" fill="none"
              stroke="#14203c" stroke-width="2.2" />
```

- [ ] **Step 4: 홈플레이트 색상 변경**

`app.py:621-624`의 다음 블록:

```python
    plate_svg = f"""
    <polygon points="{grid_cx-42},{grid_bottom_y+18} {grid_cx+42},{grid_bottom_y+18} {grid_cx+52},{grid_bottom_y+40}
                     {grid_cx},{grid_bottom_y+58} {grid_cx-52},{grid_bottom_y+40}"
             fill="#e2e8f0" stroke="#22d3ee" stroke-width="1.5" />"""
```

를 다음으로 교체:

```python
    plate_svg = f"""
    <polygon points="{grid_cx-42},{grid_bottom_y+18} {grid_cx+42},{grid_bottom_y+18} {grid_cx+52},{grid_bottom_y+40}
                     {grid_cx},{grid_bottom_y+58} {grid_cx-52},{grid_bottom_y+40}"
             fill="#ffffff" stroke="#14203c" stroke-width="1.5" />"""
```

- [ ] **Step 5: 존 밖 퍼센트 라벨 색상 미세 조정**

`app.py:607-610`의 다음 블록:

```python
    border_svg = "".join(
        f'<text x="{bx}" y="{by}" text-anchor="middle" font-size="13" fill="#64748b">{out_val:.0%}</text>'
        for bx, by in border_labels
    )
```

를 다음으로 교체:

```python
    border_svg = "".join(
        f'<text x="{bx}" y="{by}" text-anchor="middle" font-size="13" fill="#6b6555">{out_val:.0%}</text>'
        for bx, by in border_labels
    )
```

- [ ] **Step 6: 재기동 후 STRIKE ZONE BOARD 렌더 확인**

```bash
pkill -f "python -u app.py" || true
cd /Users/tina/Project/DiamondScout_AI && source venv/bin/activate && nohup python app.py > /tmp/diamondscout.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`. 브라우저로 투수 모드에서 `⚾ 분석 실행`을 눌러 STRIKE ZONE BOARD가 흰 카드 위에서 그리드 테두리·홈플레이트·궤적선이 또렷이 보이는지 확인한다 (전체 시각 검증은 Task 7에서 종합적으로 한다).

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "style: STRIKE ZONE BOARD SVG 색상을 라이트 카드 배경에 맞게 보정"
```

---

### Task 3: 결과 카드 렌더 함수 색상 통일

**Files:**
- Modify: `app.py:170-199` (`risk_level`, `render_risk_cards`)
- Modify: `app.py:1476-1530` (`render_top3_cards`, `render_hero_recommend_card`, `render_insight_card`)

**Interfaces:**
- Consumes: 없음
- Produces: 함수 시그니처 변경 없음 (반환 HTML의 인라인 색상만 교체) — `run_pitcher_analysis`/`run_batter_analysis`에서 그대로 호출하므로 호출부 수정 불필요.

- [ ] **Step 1: `risk_level`의 등급별 색상을 팔레트에 맞게 교체**

`app.py:176-180`의 다음 블록:

```python
    if value < low:
        return "낮음", "#2563eb", pct
    if value < high:
        return "보통", "#d97706", pct
    return "높음", "#dc2626", pct
```

를 다음으로 교체:

```python
    if value < low:
        return "낮음", "#1f8a4c", pct
    if value < high:
        return "보통", "#b8860b", pct
    return "높음", "#c8102e", pct
```

- [ ] **Step 2: `render_risk_cards`의 카드 배경/텍스트를 라이트 톤으로 교체**

`app.py:189-198`의 다음 블록:

```python
        cards.append(f"""
        <div style="flex:1; min-width:170px; border:1px solid {color}55; border-radius:14px; padding:18px 20px; margin:6px;
                    background:#0b1220; box-shadow: inset 0 0 12px {color}22;">
          <div style="font-size:15px; color:#94a3b8;">{label_kr}</div>
          <div style="font-size:23px; font-weight:800; color:{color}; text-shadow:0 0 8px {color}66; margin:4px 0;">{level}</div>
          <div style="font-size:14px; color:#94a3b8;">{value_text}</div>
          <div style="background:#1f2937; border-radius:6px; height:10px; margin-top:10px;">
            <div style="background:{color}; width:{pct}%; height:10px; border-radius:6px; box-shadow:0 0 6px {color};"></div>
          </div>
        </div>""")
```

를 다음으로 교체:

```python
        cards.append(f"""
        <div style="flex:1; min-width:150px; border:1px solid {color}55; border-radius:14px; padding:16px 18px; margin:4px;
                    background:#ffffff; box-shadow: 0 2px 8px rgba(20,32,60,0.06);">
          <div style="font-size:14px; color:#6b6555;">{label_kr}</div>
          <div style="font-size:22px; font-weight:800; color:{color}; margin:4px 0;">{level}</div>
          <div style="font-size:13px; color:#6b6555;">{value_text}</div>
          <div style="background:#f0ece0; border-radius:6px; height:9px; margin-top:10px;">
            <div style="background:{color}; width:{pct}%; height:9px; border-radius:6px;"></div>
          </div>
        </div>""")
```

- [ ] **Step 3: `render_top3_cards` 카드 배경/텍스트 교체**

`app.py:1478-1504`의 다음 블록:

```python
    medal_colors = ["#facc15", "#cbd5e1", "#d97706"]
    rows = []
    max_prob = max((item["probability"] for item in top3), default=1.0) or 1.0
    for i, item in enumerate(top3[:3]):
        kr = pitch_label_kr(item["pitch_label"])
        pct = item["probability"]
        bar_width = round(100 * pct / max_prob)
        color = medal_colors[i] if i < len(medal_colors) else "#94a3b8"
        rows.append(f"""
        <div style="display:flex; align-items:center; gap:14px; margin:12px 0;">
          <div style="width:32px; height:32px; border-radius:50%; background:{color}; color:#111827; font-size:15px;
                      font-weight:800; display:flex; align-items:center; justify-content:center; flex-shrink:0;">{i + 1}</div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; font-size:16px;">
              <span style="font-weight:700; color:#f1f5f9;">{kr} ({item['pitch_label']})</span>
              <span style="color:{color}; font-weight:700;">{pct:.1%}</span>
            </div>
            <div style="background:#1f2937; border-radius:6px; height:10px; margin-top:6px;">
              <div style="background:{color}; width:{bar_width}%; height:10px; border-radius:6px;"></div>
            </div>
          </div>
        </div>""")
    return f"""
    <div style="background:#0b1220; border:1px solid #1e293b; border-radius:14px; padding:18px 22px;">
      <div style="font-size:15px; color:#94a3b8; margin-bottom:10px;">{title}</div>
      {"".join(rows)}
    </div>"""
```

를 다음으로 교체:

```python
    medal_colors = ["#c8102e", "#8a8375", "#b8860b"]
    rows = []
    max_prob = max((item["probability"] for item in top3), default=1.0) or 1.0
    for i, item in enumerate(top3[:3]):
        kr = pitch_label_kr(item["pitch_label"])
        pct = item["probability"]
        bar_width = round(100 * pct / max_prob)
        color = medal_colors[i] if i < len(medal_colors) else "#6b6555"
        rows.append(f"""
        <div style="display:flex; align-items:center; gap:14px; margin:12px 0;">
          <div style="width:32px; height:32px; border-radius:50%; background:{color}; color:#ffffff; font-size:15px;
                      font-weight:800; display:flex; align-items:center; justify-content:center; flex-shrink:0;">{i + 1}</div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; font-size:16px;">
              <span style="font-weight:700; color:#14203c;">{kr} ({item['pitch_label']})</span>
              <span style="color:{color}; font-weight:700;">{pct:.1%}</span>
            </div>
            <div style="background:#f0ece0; border-radius:6px; height:10px; margin-top:6px;">
              <div style="background:{color}; width:{bar_width}%; height:10px; border-radius:6px;"></div>
            </div>
          </div>
        </div>""")
    return f"""
    <div style="background:#ffffff; border:1px solid #e6e1d3; border-radius:14px; padding:18px 22px;">
      <div style="font-size:15px; color:#6b6555; margin-bottom:10px;">{title}</div>
      {"".join(rows)}
    </div>"""
```

- [ ] **Step 4: `render_hero_recommend_card`/`render_insight_card` 배경·텍스트 교체**

`app.py:1507-1530`의 다음 블록:

```python
def render_hero_recommend_card(
    hero_label: str, hero_value: str, hero_note: str, secondary_label: str, secondary_value: str, accent: str = "#22c55e",
) -> str:
    """가장 중요한 추천 결과(추천 구종 또는 노릴 코스)를 큰 히어로 카드로, 나머지(피해야 할 구종/대응
    전략)는 아래 보조 카드로 보여준다."""
    return f"""
    <div style="background:linear-gradient(135deg, {accent}22 0%, #0b1220 70%); border:1.5px solid {accent};
                border-radius:16px; padding:22px 24px; box-shadow:0 0 22px {accent}33;">
      <div style="font-size:15px; color:#94a3b8;">{hero_label}</div>
      <div style="font-size:28px; font-weight:900; color:{accent}; margin:8px 0;">{hero_value}</div>
      <div style="font-size:14px; color:#cbd5e1;">{hero_note}</div>
    </div>
    <div style="background:#0b1220; border:1px solid #334155; border-radius:14px; padding:16px 20px; margin-top:14px;">
      <div style="font-size:15px; color:#94a3b8;">{secondary_label}</div>
      <div style="font-size:16px; color:#e5e7eb; font-weight:600; margin-top:4px;">{secondary_value}</div>
    </div>"""


def render_insight_card(title: str, text: str) -> str:
    return f"""
    <div style="background:#0b1220; border:1px solid #1e293b; border-radius:14px; padding:18px 22px;">
      <div style="font-size:15px; color:#94a3b8; margin-bottom:6px;">{title}</div>
      <div style="font-size:16px; color:#e5e7eb; line-height:1.6;">{text}</div>
    </div>"""
```

를 다음으로 교체:

```python
def render_hero_recommend_card(
    hero_label: str, hero_value: str, hero_note: str, secondary_label: str, secondary_value: str, accent: str = "#1f8a4c",
) -> str:
    """가장 중요한 추천 결과(추천 구종 또는 노릴 코스)를 큰 히어로 카드로, 나머지(피해야 할 구종/대응
    전략)는 아래 보조 카드로 보여준다."""
    return f"""
    <div style="background:linear-gradient(135deg, {accent}1a 0%, #ffffff 70%); border:1.5px solid {accent};
                border-radius:16px; padding:22px 24px;">
      <div style="font-size:15px; color:#6b6555;">{hero_label}</div>
      <div style="font-size:28px; font-weight:900; color:{accent}; margin:8px 0;">{hero_value}</div>
      <div style="font-size:14px; color:#4b463c;">{hero_note}</div>
    </div>
    <div style="background:#ffffff; border:1px solid #e6e1d3; border-radius:14px; padding:16px 20px; margin-top:14px;">
      <div style="font-size:15px; color:#6b6555;">{secondary_label}</div>
      <div style="font-size:16px; color:#14203c; font-weight:600; margin-top:4px;">{secondary_value}</div>
    </div>"""


def render_insight_card(title: str, text: str) -> str:
    return f"""
    <div style="background:#ffffff; border:1px solid #e6e1d3; border-radius:14px; padding:18px 22px;">
      <div style="font-size:15px; color:#6b6555; margin-bottom:6px;">{title}</div>
      <div style="font-size:16px; color:#14203c; line-height:1.6;">{text}</div>
    </div>"""
```

- [ ] **Step 5: 재기동 후 코칭 보드 카드 렌더 확인**

```bash
pkill -f "python -u app.py" || true
cd /Users/tina/Project/DiamondScout_AI && source venv/bin/activate && nohup python app.py > /tmp/diamondscout.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`, `/tmp/diamondscout.log`에 Traceback 없음.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "style: 코칭 보드 결과 카드(Top3/위험도/히어로/인사이트) 색상을 라이트 팔레트로 교체"
```

---

### Task 4: 위저드 진행 트랙 — 완료/현재/예정 상태별 동적 스타일

**Files:**
- Modify: `app.py:1546-1577` (`WIZARD_STEP_LABELS` 이하 스텝 전환 함수들)
- Modify: `app.py:1592-1596` (투수 모드 진행 칩 생성부)
- Modify: `app.py:1696-1703` (투수 모드 wizard outputs·바인딩)
- Modify: `app.py:1724-1728` (타자 모드 진행 칩 생성부)
- Modify: `app.py:1827-1834` (타자 모드 wizard outputs·바인딩)

**Interfaces:**
- Consumes: Task 1에서 정의한 `.ds-step-dot`/`.ds-step-done`/`.ds-step-now`/`.ds-step-next` CSS 클래스
- Produces: `_step_dot_classes(step: int) -> list[list[str]]` — 이후 태스크에서 재사용하지 않지만 6개 스텝 전환 함수가 공통으로 참조

- [ ] **Step 1: 스텝별 클래스 계산 헬퍼 추가 + 6개 전환 함수가 클래스도 함께 반환하도록 확장**

`app.py:1546-1577`의 다음 블록:

```python
WIZARD_STEP_LABELS = ["1️⃣ 매치업", "2️⃣ 상황판", "3️⃣ 베이스&스코어", "4️⃣ 작전지시"]


def _goto_step_1():
    return gr.Tabs(selected=0), 1


def _goto_step_2():
    return gr.Tabs(selected=1), 2


def _goto_step_3():
    return gr.Tabs(selected=2), 3


def _goto_step_4():
    return gr.Tabs(selected=3), 4


def _step_prev(current_step: int):
    """다음/이전 버튼은 gr.Tabs(selected=)로 카드 하나를 전환한다.
    Column 4개를 visible= 로 각각 토글하는 방식은 두 번째 전환부터 간헐적으로
    스텝형 전환을 위해 제공하는 gr.Tabs(selected=) 방식으로 바꿨다."""
    target = max(1, current_step - 1)
    return gr.Tabs(selected=target - 1), target


def _step_next(current_step: int):
    target = min(4, current_step + 1)
    return gr.Tabs(selected=target - 1), target
```

를 다음으로 교체:

```python
WIZARD_STEP_LABELS = ["1️⃣ 매치업", "2️⃣ 상황판", "3️⃣ 베이스&스코어", "4️⃣ 작전지시"]


def _step_dot_classes(step: int) -> list[list[str]]:
    """1~4번 스텝 진행 트랙 버튼에 완료(레드)/현재(네이비)/예정(연한 회색) 상태 클래스를 계산한다."""
    classes = []
    for i in range(1, 5):
        if i < step:
            classes.append(["ds-step-dot", "ds-step-done"])
        elif i == step:
            classes.append(["ds-step-dot", "ds-step-now"])
        else:
            classes.append(["ds-step-dot", "ds-step-next"])
    return classes


def _step_dot_updates(step: int):
    c = _step_dot_classes(step)
    return (
        gr.Button(elem_classes=c[0]), gr.Button(elem_classes=c[1]),
        gr.Button(elem_classes=c[2]), gr.Button(elem_classes=c[3]),
    )


def _goto_step_1():
    return (gr.Tabs(selected=0), 1, *_step_dot_updates(1))


def _goto_step_2():
    return (gr.Tabs(selected=1), 2, *_step_dot_updates(2))


def _goto_step_3():
    return (gr.Tabs(selected=2), 3, *_step_dot_updates(3))


def _goto_step_4():
    return (gr.Tabs(selected=3), 4, *_step_dot_updates(4))


def _step_prev(current_step: int):
    """다음/이전 버튼은 gr.Tabs(selected=)로 카드 하나를 전환한다.
    Column 4개를 visible= 로 각각 토글하는 방식은 두 번째 전환부터 간헐적으로
    스텝형 전환을 위해 제공하는 gr.Tabs(selected=) 방식으로 바꿨다."""
    target = max(1, current_step - 1)
    return (gr.Tabs(selected=target - 1), target, *_step_dot_updates(target))


def _step_next(current_step: int):
    target = min(4, current_step + 1)
    return (gr.Tabs(selected=target - 1), target, *_step_dot_updates(target))
```

- [ ] **Step 2: 투수 모드 진행 칩의 초기 클래스를 상태별로 지정**

`app.py:1592-1596`의 다음 블록:

```python
            with gr.Row(elem_classes=["ds-wizard-progress"]):
                p_chip1 = gr.Button(WIZARD_STEP_LABELS[0], elem_classes=["ds-chip"], size="sm")
                p_chip2 = gr.Button(WIZARD_STEP_LABELS[1], elem_classes=["ds-chip"], size="sm")
                p_chip3 = gr.Button(WIZARD_STEP_LABELS[2], elem_classes=["ds-chip"], size="sm")
                p_chip4 = gr.Button(WIZARD_STEP_LABELS[3], elem_classes=["ds-chip"], size="sm")
```

를 다음으로 교체:

```python
            with gr.Row(elem_classes=["ds-wizard-progress"]):
                p_chip1 = gr.Button(WIZARD_STEP_LABELS[0], elem_classes=["ds-step-dot", "ds-step-now"], size="sm")
                p_chip2 = gr.Button(WIZARD_STEP_LABELS[1], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                p_chip3 = gr.Button(WIZARD_STEP_LABELS[2], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                p_chip4 = gr.Button(WIZARD_STEP_LABELS[3], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
```

- [ ] **Step 3: 투수 모드 wizard outputs에 4개 칩 버튼 추가**

`app.py:1696-1703`의 다음 블록:

```python
            p_wizard_outputs = [p_wizard_tabs, p_step_state]
            p_prev_btn.click(fn=_step_prev, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_next_btn.click(fn=_step_next, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_chip1.click(fn=_goto_step_1, outputs=p_wizard_outputs)
            p_chip2.click(fn=_goto_step_2, outputs=p_wizard_outputs)
            p_chip3.click(fn=_goto_step_3, outputs=p_wizard_outputs)
            p_chip4.click(fn=_goto_step_4, outputs=p_wizard_outputs)
            p_reset_btn.click(fn=_goto_step_1, outputs=p_wizard_outputs)
```

를 다음으로 교체:

```python
            p_wizard_outputs = [p_wizard_tabs, p_step_state, p_chip1, p_chip2, p_chip3, p_chip4]
            p_prev_btn.click(fn=_step_prev, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_next_btn.click(fn=_step_next, inputs=[p_step_state], outputs=p_wizard_outputs)
            p_chip1.click(fn=_goto_step_1, outputs=p_wizard_outputs)
            p_chip2.click(fn=_goto_step_2, outputs=p_wizard_outputs)
            p_chip3.click(fn=_goto_step_3, outputs=p_wizard_outputs)
            p_chip4.click(fn=_goto_step_4, outputs=p_wizard_outputs)
            p_reset_btn.click(fn=_goto_step_1, outputs=p_wizard_outputs)
```

- [ ] **Step 4: 타자 모드에도 동일하게 적용 (진행 칩 초기 클래스)**

`app.py:1724-1728`의 다음 블록:

```python
            with gr.Row(elem_classes=["ds-wizard-progress"]):
                b_chip1 = gr.Button(WIZARD_STEP_LABELS[0], elem_classes=["ds-chip"], size="sm")
                b_chip2 = gr.Button(WIZARD_STEP_LABELS[1], elem_classes=["ds-chip"], size="sm")
                b_chip3 = gr.Button(WIZARD_STEP_LABELS[2], elem_classes=["ds-chip"], size="sm")
                b_chip4 = gr.Button(WIZARD_STEP_LABELS[3], elem_classes=["ds-chip"], size="sm")
```

를 다음으로 교체:

```python
            with gr.Row(elem_classes=["ds-wizard-progress"]):
                b_chip1 = gr.Button(WIZARD_STEP_LABELS[0], elem_classes=["ds-step-dot", "ds-step-now"], size="sm")
                b_chip2 = gr.Button(WIZARD_STEP_LABELS[1], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                b_chip3 = gr.Button(WIZARD_STEP_LABELS[2], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
                b_chip4 = gr.Button(WIZARD_STEP_LABELS[3], elem_classes=["ds-step-dot", "ds-step-next"], size="sm")
```

- [ ] **Step 5: 타자 모드 wizard outputs에 4개 칩 버튼 추가**

`app.py:1827-1834`의 다음 블록:

```python
            b_wizard_outputs = [b_wizard_tabs, b_step_state]
            b_prev_btn.click(fn=_step_prev, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_next_btn.click(fn=_step_next, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_chip1.click(fn=_goto_step_1, outputs=b_wizard_outputs)
            b_chip2.click(fn=_goto_step_2, outputs=b_wizard_outputs)
            b_chip3.click(fn=_goto_step_3, outputs=b_wizard_outputs)
            b_chip4.click(fn=_goto_step_4, outputs=b_wizard_outputs)
            b_reset_btn.click(fn=_goto_step_1, outputs=b_wizard_outputs)
```

를 다음으로 교체:

```python
            b_wizard_outputs = [b_wizard_tabs, b_step_state, b_chip1, b_chip2, b_chip3, b_chip4]
            b_prev_btn.click(fn=_step_prev, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_next_btn.click(fn=_step_next, inputs=[b_step_state], outputs=b_wizard_outputs)
            b_chip1.click(fn=_goto_step_1, outputs=b_wizard_outputs)
            b_chip2.click(fn=_goto_step_2, outputs=b_wizard_outputs)
            b_chip3.click(fn=_goto_step_3, outputs=b_wizard_outputs)
            b_chip4.click(fn=_goto_step_4, outputs=b_wizard_outputs)
            b_reset_btn.click(fn=_goto_step_1, outputs=b_wizard_outputs)
```

- [ ] **Step 6: 재기동 후 스텝 전환 시 진행 트랙 상태 변화 확인**

```bash
pkill -f "python -u app.py" || true
cd /Users/tina/Project/DiamondScout_AI && source venv/bin/activate && nohup python app.py > /tmp/diamondscout.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`. 브라우저로 투수 모드 `다음 ➡`을 2~3번 눌러 지나온 스텝은 레드, 현재 스텝은 네이비 배경, 남은 스텝은 연한 회색으로 바뀌는지 확인 (`p_chip1.click`처럼 진행 트랙을 직접 클릭해 임의 스텝으로 이동해도 동일하게 반영되는지 확인).

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: 위저드 진행 트랙에 완료/현재/예정 상태별 동적 스타일 적용"
```

---

### Task 5: "현재 매치업" 요약 패널 추가 (데스크톱 전용)

**Files:**
- Modify: `app.py:1598-1636` (투수 모드 위저드 Tabs 블록을 Row/Column으로 감싸고 요약 패널 추가)
- Modify: `app.py:1730-1768` (타자 모드 동일 적용)
- Modify: `app.py` — `_render_strike_zone_board` 근처에 신규 함수 `render_matchup_summary` 추가, 각 탭에 `.change()` 바인딩 추가

**Interfaces:**
- Consumes: Task 1의 `.ds-matchup-panel` CSS (기본 `display:none`, `≥1280px`에서 `display:block`)
- Produces: `render_matchup_summary(pitcher_label, batter_label, balls, strikes, outs, inning, topbot) -> str` — 투수/타자 두 탭이 동일 함수를 공유

- [ ] **Step 1: `render_matchup_summary` 함수 추가**

`app.py:1539`(`render_analysis_status` 함수 끝) 바로 다음 줄에 아래 함수를 추가한다:

```python
def render_matchup_summary(pitcher_label, batter_label, balls, strikes, outs, inning, topbot) -> str:
    """데스크톱(≥1280px) 2단 레이아웃 우측에 상시 노출되는 "현재 매치업" 요약 패널.
    위저드 스텝을 넘나드는 동안에도 지금까지 입력한 값을 다시 스크롤하지 않고 확인할 수 있게 한다.
    모바일/태블릿에서는 .ds-matchup-panel이 display:none이라 이 패널 자체가 안 보이므로,
    좁은 화면에서는 기존과 동일하게 STEP 1로 돌아가야 매치업을 다시 확인할 수 있다."""
    topbot_short = "초" if "초" in topbot else "말"
    return f"""
    <div class="ds-mp-title">현재 매치업</div>
    <div class="ds-mp-row"><span>투수</span><span>{pitcher_label}</span></div>
    <div class="ds-mp-row"><span>타자</span><span>{batter_label}</span></div>
    <div class="ds-mp-row"><span>카운트</span><span>{balls}B - {strikes}S, {outs}아웃</span></div>
    <div class="ds-mp-row"><span>이닝</span><span>{inning}회 {topbot_short}</span></div>
    """
```

- [ ] **Step 2: 투수 모드 — 위저드 Tabs를 Row/Column으로 감싸고 매치업 패널 추가**

`app.py:1598-1636`의 다음 블록 (`with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as p_wizard_tabs:` 부터 STEP 4 작전지시 텍스트박스까지):

```python
            with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as p_wizard_tabs:
                with gr.Tab("매치업", id=0):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 1 · 매치업</div>')
                        with gr.Row():
                            p_pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="내 투수 ID")
                            p_batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="상대 타자 ID")
                        gr.Markdown("좌타/우타·좌투/우투는 데이터에서 자동으로 추정됩니다.")

                with gr.Tab("상황판", id=1):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 2 · 상황판</div>')
                        gr.Markdown("#### ⚾ 카운트 스코어보드")
                        with gr.Row(elem_classes=["ds-scoreboard"]):
                            p_balls_input = gr.Slider(0, 3, value=0, step=1, label="볼")
                            p_strikes_input = gr.Slider(0, 2, value=0, step=1, label="스트라이크")
                            p_outs_input = gr.Slider(0, 2, value=2, step=1, label="아웃")
                        with gr.Row():
                            p_inning_input = gr.Number(value=1, precision=0, label="이닝")
                            p_topbot_input = gr.Radio(["초(Top)", "말(Bot)"], value="초(Top)", label="이닝 초/말")

                with gr.Tab("베이스 & 스코어", id=2):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 3 · 베이스 & 스코어</div>')
                        gr.Markdown("#### 🔶 주자 상황")
                        with gr.Row():
                            p_on1b_input = gr.Checkbox(value=False, label="1루 주자", elem_classes=["ds-base-card"])
                            p_on2b_input = gr.Checkbox(value=False, label="2루 주자", elem_classes=["ds-base-card"])
                            p_on3b_input = gr.Checkbox(value=False, label="3루 주자", elem_classes=["ds-base-card"])
                        gr.Markdown("#### ⚾ 스코어")
                        with gr.Row():
                            p_our_score_input = gr.Number(value=0, precision=0, label="우리팀 점수")
                            gr.Markdown("<div style='text-align:center; padding-top:28px; font-weight:800;'>:</div>")
                            p_opponent_score_input = gr.Number(value=0, precision=0, label="상대팀 점수")

                with gr.Tab("작전 지시", id=3):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 4 · 작전 지시</div>')
                        p_comment_input = gr.Textbox(value=DEFAULT_COMMENT_PITCHER, label="🎙️ 코치에게 전달할 전략 의도", lines=2)
```

를 다음으로 교체 (전체를 `gr.Row` + `gr.Column(scale=3)`으로 한 단 더 감싸고, 매치업 패널 `gr.Column`을 형제로 추가):

```python
            with gr.Row():
                with gr.Column(scale=3):
                    with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as p_wizard_tabs:
                        with gr.Tab("매치업", id=0):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 1 · 매치업</div>')
                                with gr.Row():
                                    p_pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="내 투수 ID")
                                    p_batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="상대 타자 ID")
                                gr.Markdown("좌타/우타·좌투/우투는 데이터에서 자동으로 추정됩니다.")

                        with gr.Tab("상황판", id=1):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 2 · 상황판</div>')
                                gr.Markdown("#### ⚾ 카운트 스코어보드")
                                with gr.Row(elem_classes=["ds-scoreboard"]):
                                    p_balls_input = gr.Slider(0, 3, value=0, step=1, label="볼")
                                    p_strikes_input = gr.Slider(0, 2, value=0, step=1, label="스트라이크")
                                    p_outs_input = gr.Slider(0, 2, value=2, step=1, label="아웃")
                                with gr.Row():
                                    p_inning_input = gr.Number(value=1, precision=0, label="이닝")
                                    p_topbot_input = gr.Radio(["초(Top)", "말(Bot)"], value="초(Top)", label="이닝 초/말")

                        with gr.Tab("베이스 & 스코어", id=2):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 3 · 베이스 & 스코어</div>')
                                gr.Markdown("#### 🔶 주자 상황")
                                with gr.Row():
                                    p_on1b_input = gr.Checkbox(value=False, label="1루 주자", elem_classes=["ds-base-card"])
                                    p_on2b_input = gr.Checkbox(value=False, label="2루 주자", elem_classes=["ds-base-card"])
                                    p_on3b_input = gr.Checkbox(value=False, label="3루 주자", elem_classes=["ds-base-card"])
                                gr.Markdown("#### ⚾ 스코어")
                                with gr.Row():
                                    p_our_score_input = gr.Number(value=0, precision=0, label="우리팀 점수")
                                    gr.Markdown("<div style='text-align:center; padding-top:28px; font-weight:800;'>:</div>")
                                    p_opponent_score_input = gr.Number(value=0, precision=0, label="상대팀 점수")

                        with gr.Tab("작전 지시", id=3):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 4 · 작전 지시</div>')
                                p_comment_input = gr.Textbox(value=DEFAULT_COMMENT_PITCHER, label="🎙️ 코치에게 전달할 전략 의도", lines=2)

                with gr.Column(scale=2, elem_classes=["ds-matchup-panel"]):
                    p_matchup_output = gr.HTML(
                        render_matchup_summary(DEFAULT_PITCHER_ID, DEFAULT_BATTER_ID, 0, 0, 2, 1, "초(Top)")
                    )
```

- [ ] **Step 3: 투수 모드 — 매치업 패널을 관련 입력 변경 시 갱신**

`app.py`에서 `p_wizard_outputs = [...]` 정의 줄(Task 4에서 수정한 줄) 바로 다음에 아래를 추가한다:

```python
            p_matchup_inputs = [
                p_pitcher_id_input, p_batter_id_input, p_balls_input, p_strikes_input,
                p_outs_input, p_inning_input, p_topbot_input,
            ]
            for comp in p_matchup_inputs:
                comp.change(fn=render_matchup_summary, inputs=p_matchup_inputs, outputs=[p_matchup_output])
```

- [ ] **Step 4: 타자 모드 — 동일하게 Row/Column 감싸기 + 매치업 패널 추가**

`app.py:1730-1768`의 다음 블록 (타자 모드의 `with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as b_wizard_tabs:` 부터 STEP 4 텍스트박스까지):

```python
            with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as b_wizard_tabs:
                with gr.Tab("매치업", id=0):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 1 · 매치업</div>')
                        with gr.Row():
                            b_batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="내 타자 ID")
                            b_pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="상대 투수 ID")
                        gr.Markdown("좌타/우타·좌투/우투는 데이터에서 자동으로 추정됩니다.")

                with gr.Tab("상황판", id=1):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 2 · 상황판</div>')
                        gr.Markdown("#### ⚾ 카운트 스코어보드")
                        with gr.Row(elem_classes=["ds-scoreboard"]):
                            b_balls_input = gr.Slider(0, 3, value=0, step=1, label="볼")
                            b_strikes_input = gr.Slider(0, 2, value=0, step=1, label="스트라이크")
                            b_outs_input = gr.Slider(0, 2, value=2, step=1, label="아웃")
                        with gr.Row():
                            b_inning_input = gr.Number(value=1, precision=0, label="이닝")
                            b_topbot_input = gr.Radio(["초(Top)", "말(Bot)"], value="초(Top)", label="이닝 초/말")

                with gr.Tab("베이스 & 스코어", id=2):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 3 · 베이스 & 스코어</div>')
                        gr.Markdown("#### 🔶 주자 상황")
                        with gr.Row():
                            b_on1b_input = gr.Checkbox(value=False, label="1루 주자", elem_classes=["ds-base-card"])
                            b_on2b_input = gr.Checkbox(value=False, label="2루 주자", elem_classes=["ds-base-card"])
                            b_on3b_input = gr.Checkbox(value=False, label="3루 주자", elem_classes=["ds-base-card"])
                        gr.Markdown("#### ⚾ 스코어")
                        with gr.Row():
                            b_our_score_input = gr.Number(value=0, precision=0, label="우리팀 점수")
                            gr.Markdown("<div style='text-align:center; padding-top:28px; font-weight:800;'>:</div>")
                            b_opponent_score_input = gr.Number(value=0, precision=0, label="상대팀 점수")

                with gr.Tab("작전 지시", id=3):
                    with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                        gr.HTML('<div class="ds-panel-title">🕹️ STEP 4 · 작전 지시</div>')
                        b_comment_input = gr.Textbox(value=DEFAULT_COMMENT_BATTER, label="🎙️ 코치에게 전달할 전략 의도", lines=2)
```

를 다음으로 교체:

```python
            with gr.Row():
                with gr.Column(scale=3):
                    with gr.Tabs(elem_classes=["ds-wizard-tabs"]) as b_wizard_tabs:
                        with gr.Tab("매치업", id=0):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 1 · 매치업</div>')
                                with gr.Row():
                                    b_batter_id_input = gr.Dropdown(choices=DEMO_BATTER_CHOICES, value=DEFAULT_BATTER_ID, label="내 타자 ID")
                                    b_pitcher_id_input = gr.Dropdown(choices=DEMO_PITCHER_CHOICES, value=DEFAULT_PITCHER_ID, label="상대 투수 ID")
                                gr.Markdown("좌타/우타·좌투/우투는 데이터에서 자동으로 추정됩니다.")

                        with gr.Tab("상황판", id=1):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 2 · 상황판</div>')
                                gr.Markdown("#### ⚾ 카운트 스코어보드")
                                with gr.Row(elem_classes=["ds-scoreboard"]):
                                    b_balls_input = gr.Slider(0, 3, value=0, step=1, label="볼")
                                    b_strikes_input = gr.Slider(0, 2, value=0, step=1, label="스트라이크")
                                    b_outs_input = gr.Slider(0, 2, value=2, step=1, label="아웃")
                                with gr.Row():
                                    b_inning_input = gr.Number(value=1, precision=0, label="이닝")
                                    b_topbot_input = gr.Radio(["초(Top)", "말(Bot)"], value="초(Top)", label="이닝 초/말")

                        with gr.Tab("베이스 & 스코어", id=2):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 3 · 베이스 & 스코어</div>')
                                gr.Markdown("#### 🔶 주자 상황")
                                with gr.Row():
                                    b_on1b_input = gr.Checkbox(value=False, label="1루 주자", elem_classes=["ds-base-card"])
                                    b_on2b_input = gr.Checkbox(value=False, label="2루 주자", elem_classes=["ds-base-card"])
                                    b_on3b_input = gr.Checkbox(value=False, label="3루 주자", elem_classes=["ds-base-card"])
                                gr.Markdown("#### ⚾ 스코어")
                                with gr.Row():
                                    b_our_score_input = gr.Number(value=0, precision=0, label="우리팀 점수")
                                    gr.Markdown("<div style='text-align:center; padding-top:28px; font-weight:800;'>:</div>")
                                    b_opponent_score_input = gr.Number(value=0, precision=0, label="상대팀 점수")

                        with gr.Tab("작전 지시", id=3):
                            with gr.Column(elem_classes=["ds-panel", "ds-wizard-card"]):
                                gr.HTML('<div class="ds-panel-title">🕹️ STEP 4 · 작전 지시</div>')
                                b_comment_input = gr.Textbox(value=DEFAULT_COMMENT_BATTER, label="🎙️ 코치에게 전달할 전략 의도", lines=2)

                with gr.Column(scale=2, elem_classes=["ds-matchup-panel"]):
                    b_matchup_output = gr.HTML(
                        render_matchup_summary(DEFAULT_PITCHER_ID, DEFAULT_BATTER_ID, 0, 0, 2, 1, "초(Top)")
                    )
```

(주의: 타자 모드 STEP 1은 `b_batter_id_input`이 먼저, `b_pitcher_id_input`이 나중에 선언된다. `render_matchup_summary`는 `pitcher_label`을 첫 인자로 받으므로 Step 5의 `b_matchup_inputs` 순서에서 `b_pitcher_id_input`을 먼저 넣어야 한다.)

- [ ] **Step 5: 타자 모드 — 매치업 패널을 관련 입력 변경 시 갱신**

`app.py`에서 `b_wizard_outputs = [...]` 정의 줄(Task 4에서 수정한 줄) 바로 다음에 아래를 추가한다:

```python
            b_matchup_inputs = [
                b_pitcher_id_input, b_batter_id_input, b_balls_input, b_strikes_input,
                b_outs_input, b_inning_input, b_topbot_input,
            ]
            for comp in b_matchup_inputs:
                comp.change(fn=render_matchup_summary, inputs=b_matchup_inputs, outputs=[b_matchup_output])
```

- [ ] **Step 6: 재기동 후 데스크톱 폭에서 매치업 패널 노출·갱신 확인**

```bash
pkill -f "python -u app.py" || true
cd /Users/tina/Project/DiamondScout_AI && source venv/bin/activate && nohup python app.py > /tmp/diamondscout.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`, Traceback 없음. 브라우저 창을 1280px 이상으로 넓혀 우측에 "현재 매치업" 패널이 나타나는지, 투수/타자 ID를 바꾸거나 카운트 슬라이더를 조작하면 패널 값이 즉시 갱신되는지 확인. 1279px 이하로 좁히면 패널이 사라지고 위저드 카드가 전체 폭을 쓰는지 확인.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: 데스크톱 전용 '현재 매치업' 요약 패널 추가 (투수/타자 모드)"
```

---

### Task 6: 결과 화면 벤토 그리드 레이아웃 적용

**Files:**
- Modify: `app.py:1647-1667` (투수 모드 코칭 보드 결과 섹션)
- Modify: `app.py:1778-1798` (타자 모드 코칭 보드 결과 섹션)

**Interfaces:**
- Consumes: Task 1의 `.ds-bento`/`.ds-bento-wide` CSS (모바일/태블릿 2열, 데스크톱 4열, wide는 전체 폭)
- Produces: 없음 (기존 `gr.HTML`/`gr.Markdown` 컴포넌트 변수명 전부 유지 — `run_pitcher_analysis`/`run_batter_analysis`의 `outputs=` 리스트는 변경 불필요)

- [ ] **Step 1: 투수 모드 — 추천 구종/상대 타자 약점/위험도/STRIKE ZONE BOARD를 벤토 그리드로 재배치**

`app.py:1647-1667`의 다음 블록:

```python
            with gr.Group(elem_classes=["ds-board"]):
                gr.HTML('<div class="ds-board-title">🧠 코칭 보드</div>')
                p_hand_output = gr.Markdown()
                p_top3_output = gr.HTML()

                gr.Markdown("#### 🎯 추천 구종")
                p_recommend_card_output = gr.HTML()

                gr.Markdown("#### 🧑‍💼 상대 타자 약점")
                p_batter_weakness_output = gr.HTML()

                gr.Markdown("#### ⚠️ 위험도 카드")
                p_risk_html_output = gr.HTML(label="위험도 요약")

                gr.Markdown("#### 🌐 STRIKE ZONE BOARD")
                p_hotcold_plot = gr.HTML()

                gr.Markdown("#### 📄 전략 리포트")
                p_report_output = gr.Markdown()
                p_pdf_btn = gr.Button("📄 PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                p_pdf_file_output = gr.File(label="다운로드 파일")
```

를 다음으로 교체:

```python
            with gr.Group(elem_classes=["ds-board"]):
                gr.HTML('<div class="ds-board-title">🧠 코칭 보드</div>')
                p_hand_output = gr.Markdown()
                p_top3_output = gr.HTML()

                with gr.Row(elem_classes=["ds-bento"]):
                    with gr.Column():
                        gr.Markdown("#### 🎯 추천 구종")
                        p_recommend_card_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### 🧑‍💼 상대 타자 약점")
                        p_batter_weakness_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### ⚠️ 위험도 카드")
                        p_risk_html_output = gr.HTML(label="위험도 요약")
                    with gr.Column(elem_classes=["ds-bento-wide"]):
                        gr.Markdown("#### 🌐 STRIKE ZONE BOARD")
                        p_hotcold_plot = gr.HTML()

                gr.Markdown("#### 📄 전략 리포트")
                p_report_output = gr.Markdown()
                p_pdf_btn = gr.Button("📄 PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                p_pdf_file_output = gr.File(label="다운로드 파일")
```

- [ ] **Step 2: 타자 모드 — 동일하게 벤토 그리드 적용**

`app.py:1778-1798`의 다음 블록:

```python
            with gr.Group(elem_classes=["ds-board"]):
                gr.HTML('<div class="ds-board-title">🧠 코칭 보드</div>')
                b_hand_output = gr.Markdown()
                b_top3_output = gr.HTML()

                gr.Markdown("#### 🎯 노릴 코스 / 대응 전략")
                b_recommend_card_output = gr.HTML()

                gr.Markdown("#### 🧑‍💼 상대 투수 패턴")
                b_pitcher_pattern_output = gr.HTML()

                gr.Markdown("#### ⚠️ 위험도 카드")
                b_risk_html_output = gr.HTML(label="위험도 요약")

                gr.Markdown("#### 🌐 STRIKE ZONE BOARD")
                b_hotcold_plot = gr.HTML()

                gr.Markdown("#### 📄 전략 리포트")
                b_report_output = gr.Markdown()
                b_pdf_btn = gr.Button("📄 PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                b_pdf_file_output = gr.File(label="다운로드 파일")
```

를 다음으로 교체:

```python
            with gr.Group(elem_classes=["ds-board"]):
                gr.HTML('<div class="ds-board-title">🧠 코칭 보드</div>')
                b_hand_output = gr.Markdown()
                b_top3_output = gr.HTML()

                with gr.Row(elem_classes=["ds-bento"]):
                    with gr.Column():
                        gr.Markdown("#### 🎯 노릴 코스 / 대응 전략")
                        b_recommend_card_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### 🧑‍💼 상대 투수 패턴")
                        b_pitcher_pattern_output = gr.HTML()
                    with gr.Column():
                        gr.Markdown("#### ⚠️ 위험도 카드")
                        b_risk_html_output = gr.HTML(label="위험도 요약")
                    with gr.Column(elem_classes=["ds-bento-wide"]):
                        gr.Markdown("#### 🌐 STRIKE ZONE BOARD")
                        b_hotcold_plot = gr.HTML()

                gr.Markdown("#### 📄 전략 리포트")
                b_report_output = gr.Markdown()
                b_pdf_btn = gr.Button("📄 PDF 리포트 다운로드 생성", elem_classes=["ds-btn-pdf"])
                b_pdf_file_output = gr.File(label="다운로드 파일")
```

- [ ] **Step 3: 재기동 후 벤토 그리드 반응형 확인**

```bash
pkill -f "python -u app.py" || true
cd /Users/tina/Project/DiamondScout_AI && source venv/bin/activate && nohup python app.py > /tmp/diamondscout.log 2>&1 &
sleep 8
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`, Traceback 없음. 투수 모드에서 `⚾ 분석 실행` 후, 좁은 화면(모바일)에서는 결과 카드가 2열, 1280px 이상에서는 4열(STRIKE ZONE BOARD는 전체 폭)로 배치되는지 확인.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: 코칭 보드 결과 화면을 벤토 그리드 레이아웃으로 재구성"
```

---

### Task 7: 전체 화면 수동 시각 검증 (모바일/데스크톱)

**Files:** 없음 (검증 전용 태스크, 코드 변경 없음)

**Interfaces:**
- Consumes: Task 1~6에서 완성된 모든 변경사항
- Produces: 없음

- [ ] **Step 1: 서버 기동 상태 재확인**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7862
```

Expected: `200`. 아니라면 Task 6 Step 3와 동일한 재기동 절차를 다시 수행한다.

- [ ] **Step 2: 데스크톱 폭에서 투수 모드 전체 플로우 확인**

브라우저(claude-in-chrome 또는 수동)로 `http://localhost:7862` 접속, 창 폭 1280px 이상 확보 후:
- 진행 트랙 4개 스텝을 순서대로 클릭/`다음 ➡`으로 통과하며 완료(레드)/현재(네이비)/예정(회색) 색이 올바른지 확인
- STEP 1에서 투수/타자 ID를 바꾸면 우측 "현재 매치업" 패널이 즉시 갱신되는지 확인
- 마지막 스텝에서 `⚾ 분석 실행` 클릭 → 코칭 보드가 4열 벤토 그리드로 나오고, STRIKE ZONE BOARD가 흰 카드 위에서 그리드/궤적/추천 셀 마커가 잘 보이는지 확인
- `📄 PDF 리포트 다운로드 생성` 버튼이 아웃라인 네이비 스타일로 다른 Gradio 기본 버튼과 이질감 없이 보이는지 확인
- `🔄 다시 분석` 클릭 시 STEP 1로 돌아가고 진행 트랙이 초기화되는지 확인

- [ ] **Step 3: 모바일 폭(375~390px)에서 동일 플로우 확인**

브라우저 창(또는 디바이스 툴바)을 375~390px로 좁혀서:
- "현재 매치업" 패널이 사라지고 위저드 카드가 전체 폭을 쓰는지 확인
- 진행 트랙 라벨 글자가 잘리지 않고 4칸이 한 줄에 들어가는지 확인
- 결과 화면이 2열 벤토 그리드로 배치되는지 확인
- 가로 스크롤이 발생하지 않는지 확인 (발생 시 원인이 된 요소의 `width`/`min-width`를 찾아 수정)

- [ ] **Step 4: 타자 모드도 Step 2~3과 동일하게 확인**

투수 모드와 구조가 동일하므로 회귀만 빠르게 훑는다: 진행 트랙, 매치업 패널, 벤토 그리드, PDF 버튼, 다시 분석.

- [ ] **Step 5: 문제 발견 시 해당 Task로 돌아가 수정 후 재검증**

발견된 문제는 원인이 된 Task(예: 색 대비 문제 → Task 2/3, 레이아웃 깨짐 → Task 5/6)로 돌아가 수정하고, 같은 파일을 다시 커밋한다 (새 커밋으로, 기존 커밋 amend 금지).

- [ ] **Step 6: 최종 확인 커밋 (변경사항이 있었던 경우만)**

Step 5에서 추가 수정이 있었다면 그 시점에 이미 커밋했을 것이므로 별도 커밋 불필요. 수정 없이 전부 통과했다면 이 태스크는 커밋 없이 종료한다.

---

## Self-Review 결과

- **스펙 커버리지**: 색상 팔레트 교체(Task 1), 버튼 2종 통일(Task 1), STRIKE ZONE BOARD 카드 톤(Task 1) + 내부 SVG 대비 보정(Task 2), 결과 카드 색상 통일(Task 3), 진행 표시 완료/현재/예정 구분(Task 4), 데스크톱 2단 + 매치업 패널(Task 5), 벤토 그리드(Task 6), 반응형 브레이크포인트(Task 1 CSS + Task 7 검증) — 설계 문서의 모든 섹션에 대응하는 태스크가 있다.
- **플레이스홀더 스캔**: "TBD"/"나중에" 등 미확정 표현 없음. 모든 코드 스텝에 실제 diff 내용이 포함되어 있다.
- **타입/시그니처 일관성**: `render_matchup_summary`가 Task 5에서 정의한 파라미터 순서(`pitcher_label, batter_label, balls, strikes, outs, inning, topbot`)를 Step 3(투수)/Step 5(타자)의 `inputs=` 리스트 순서와 일치시켰다. `_step_dot_updates`가 반환하는 4-튜플이 `p_wizard_outputs`/`b_wizard_outputs`의 뒤 4개 항목(`p_chip1..4`/`b_chip1..4`) 순서와 일치한다.
- **범위 체크**: 전부 `app.py` 단일 파일, `services/*`/`models/*` 미변경, 위저드 스텝 순서·`gr.State` 전환 메커니즘 미변경 — 스펙의 "비대상" 조건을 지켰다.
