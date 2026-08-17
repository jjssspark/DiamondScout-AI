"""DiamondScout AI 전역 스타일.

2026-08-04 라이트 브로드캐스트 팔레트를 유지한다 (팔레트 10색 외 색상은 쓰지 않는다).
2026-08-16 4단계 위저드를 걷어내고 한 화면 3열 "덕아웃 콘솔"로 교체하면서, 위저드/랜딩/
구(舊) 다이아몬드 전용 규칙은 사용처가 사라져 함께 제거했다. 콘솔 규칙은
output/mockups/dugout-console.html에서 가져오되, 셀렉터 이름은 ui/console.py 렌더러가
실제로 뱉는 이름(ds-lamp--on / ds-base--occupied)에 맞춰 옮겼다.
"""

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Teko:wght@500;600;700&family=Share+Tech+Mono&display=swap');

:root {
    color-scheme: light;
}
.gradio-container {
    background: #f4f2ec !important;
    max-width: 1560px !important;
    margin: 0 auto !important;
    font-size: 17px !important;
    color-scheme: light;
    /* Gradio 6 내부 컴포넌트(라디오/드롭다운 등)가 라이트 팔레트를 그대로 쓰도록
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
.gradio-container button, .ds-card__title {
    font-family: 'Teko', 'Pretendard', sans-serif !important;
    letter-spacing: 0.02em;
}
.gradio-container input,
.gradio-container textarea,
.gradio-container select {
    background: #f7f5ef !important;
    color: #14203c !important;
}
.gradio-container h1 { color: #14203c; font-size: 34px !important; margin-bottom: 6px !important; }
.gradio-container h2 { color: #14203c; font-size: 25px !important; }
.gradio-container h3, .gradio-container h4 {
    color: #14203c; font-size: 21px !important; margin-top: 26px !important; margin-bottom: 12px !important;
}
/* 입력 컴포넌트 라벨/텍스트 가독성 */
.gradio-container label span, .gradio-container .label-wrap span { font-size: 16.5px !important; }

/* ===== 상단 바 ===== */
.ds-top {
    background: #14203c; border-radius: 14px; padding: 14px 20px; margin-bottom: 16px;
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 18px;
}
.ds-top .ds-brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.ds-top .ds-brand__mark {
    width: 18px; height: 18px; background: #c8102e; transform: rotate(45deg); border-radius: 3px; flex: none;
}
.ds-top .ds-brand__word {
    font-family: 'Teko', sans-serif; font-size: 26px; font-weight: 900; letter-spacing: 0.13em;
    text-transform: uppercase; color: #ffffff;
}
.ds-top .ds-brand__sub { font-size: 13px; font-weight: 700; letter-spacing: 0.1em; color: #e6e1d3; }
.ds-top .ds-top__note { font-size: 13px; color: #e6e1d3; word-break: keep-all; }

/* ===== 덕아웃 콘솔 레이아웃 ===== */
/* gr.Row(flex)를 grid로 바꿔 3:5:4 비율을 직접 고정한다. scale= 값과 같은 비율이다. */
.ds-console {
    display: grid !important;
    grid-template-columns: 3fr 5fr 4fr;
    gap: 16px !important;
    align-items: start !important;
    flex-wrap: nowrap !important;
}
.ds-console > * { min-width: 0 !important; }
.ds-col-matchup, .ds-col-zone, .ds-col-result {
    display: flex !important; flex-direction: column; gap: 14px !important; min-width: 0 !important;
}

.ds-card {
    background: #ffffff !important;
    border: 1px solid #e6e1d3 !important;
    border-radius: 16px !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 6px 18px rgba(0,0,0,0.05) !important;
    padding: 16px 18px !important;
    min-width: 0 !important;
}
.ds-card__title {
    font-size: 21px; font-weight: 800; letter-spacing: 0.03em; color: #14203c;
    border-left: 4px solid #c8102e; padding-left: 10px; margin-bottom: 10px;
}
.ds-ctrl__label {
    font-size: 11px; font-weight: 800; letter-spacing: 0.14em; text-transform: uppercase;
    color: #6b6555; margin: 16px 0 8px;
}

/* ===== 버튼: Primary(레드 배경 + 흰 텍스트) / Ghost(투명 + 네이비 테두리) 2종만 ===== */
.gradio-container button { font-size: 16.5px !important; border-radius: 8px !important; }
.ds-btn--primary {
    background: #c8102e !important; color: #ffffff !important; border: 1px solid #c8102e !important;
    font-weight: 800 !important; min-height: 44px !important; box-shadow: 0 2px 0 rgba(0,0,0,0.12) !important;
}
.ds-btn--primary:hover { filter: brightness(0.88); }
.ds-btn--primary:active { transform: translateY(1px); box-shadow: none !important; }
.ds-btn--ghost {
    background: transparent !important; color: #14203c !important; border: 1.5px solid #14203c !important;
    font-weight: 800 !important; min-height: 44px !important; box-shadow: none !important;
}
.ds-btn--ghost:hover { background: rgba(20,32,60,0.06) !important; }
.ds-btn:focus-visible { outline: 3px solid #c8102e; outline-offset: 2px; }

/* ===== 좌: 매치업 ===== */
.ds-matchup { display: flex; flex-direction: column; }
.ds-mu-role {
    display: inline-block; font-size: 10.5px; font-weight: 800; letter-spacing: 0.12em;
    padding: 3px 9px; border-radius: 999px; margin-bottom: 6px;
}
.ds-mu-slot--mine  .ds-mu-role { background: rgba(20,32,60,0.09); color: #14203c; }
.ds-mu-slot--rival .ds-mu-role { background: rgba(200,16,46,0.09); color: #c8102e; }
.ds-mu-slot--mine  .ds-player-card { border-left: 4px solid #14203c; }
.ds-mu-slot--rival .ds-player-card { border-left: 4px solid #c8102e; }
.ds-vs { display: flex; align-items: center; gap: 10px; margin: 14px 0; }
.ds-vs::before, .ds-vs::after { content: ""; flex: 1; height: 1px; background: #e6e1d3; }
.ds-vs .ds-vs__txt { font-size: 12px; font-weight: 900; letter-spacing: 0.22em; color: #c8102e; }

/* 선수 카드 (ui/console.py render_player_card) */
.ds-player-card {
    border: 1px solid #e6e1d3; border-radius: 12px; padding: 13px 14px; background: #ffffff;
}
.ds-player-card .ds-player-name {
    font-size: 21px; font-weight: 900; color: #14203c; line-height: 1.2; word-break: keep-all;
}
.ds-player-card .ds-player-meta { font-size: 12.5px; color: #6b6555; margin-top: 3px; word-break: keep-all; }
.ds-player-gauges { margin-top: 11px; display: flex; flex-direction: column; gap: 9px; }
.ds-gauge-row {
    display: grid; grid-template-columns: 1fr 84px 42px; align-items: center; gap: 8px; font-size: 12px;
}
.ds-gauge-row .ds-gauge-label { color: #6b6555; font-weight: 700; }
.ds-gauge-track {
    display: block; height: 8px; border-radius: 999px; background: #f7f5ef;
    border: 1px solid #e6e1d3; overflow: hidden;
}
.ds-gauge-fill { display: block; height: 100%; background: #14203c; border-radius: 999px; }
.ds-gauge-row .ds-gauge-value {
    font-family: 'Share Tech Mono', monospace; font-weight: 800; text-align: right; color: #14203c;
}

/* ===== 중: 상황 조작 — 볼카운트 불 ===== */
/* 램프 HTML(표시 전용) 위에 투명 gr.Button 3개를 겹쳐, 램프 줄 자체가 클릭 대상이 되게 한다.
   두 레이어 모두 같은 52px 3행 그리드라 행 높이가 어긋나지 않는다. */
.ds-lamp-stack { position: relative !important; gap: 0 !important; }
.ds-lamp-stack .html-container { padding: 0 !important; margin: 0 !important; }
.ds-count-lamps { display: grid; grid-template-rows: repeat(3, 52px); align-content: start; }
.ds-lamp-group { display: flex; align-items: center; gap: 8px; height: 52px; }
.ds-lamp-label {
    width: 26px; flex: none; font-family: 'Share Tech Mono', monospace;
    font-weight: 800; font-size: 16px; color: #14203c;
}
.ds-lamp {
    display: inline-block; width: 26px; height: 26px; border-radius: 50%;
    border: 2px solid #14203c; margin-right: 6px; flex: none;
}
.ds-lamp--on  { background: #c8102e; border-color: #c8102e; box-shadow: 0 0 0 3px rgba(200,16,46,0.15); }
.ds-lamp--off { background: transparent; }
.ds-lamp-hits {
    position: absolute !important; inset: 0; z-index: 4;
    display: grid !important; grid-template-rows: repeat(3, 52px) !important;
    gap: 0 !important; padding: 0 !important; min-width: 0 !important;
}
.ds-hit-btn {
    opacity: 0; width: 100% !important; height: 100% !important;
    min-height: 52px !important; padding: 0 !important; margin: 0 !important;
    border: none !important; background: transparent !important; cursor: pointer;
}
/* 키보드 사용자는 투명 버튼이 어디 있는지 보여야 한다 */
.ds-hit-btn:focus-visible {
    opacity: 1; background: rgba(20,32,60,0.06) !important;
    outline: 3px solid #c8102e; outline-offset: -3px;
}

/* ===== 중: 상황 조작 — 주자 다이아몬드 ===== */
.ds-diamond-stack {
    position: relative !important; width: 210px !important; flex: none !important;
    margin: 0 auto !important; gap: 0 !important; min-width: 210px !important;
}
.ds-diamond-stack .html-container { padding: 0 !important; margin: 0 !important; }
.ds-diamond { width: 210px; height: 210px; }
.ds-diamond-svg { display: block; width: 210px; height: 210px; }
.ds-base { fill: #ffffff; stroke: #14203c; stroke-width: 2; }
.ds-base--occupied { fill: #c8102e; stroke: #c8102e; }
.ds-home { fill: #14203c; }
.ds-base-hits { position: absolute !important; inset: 0; z-index: 4; padding: 0 !important; }
.ds-base-hit {
    position: absolute !important; width: 52px !important; height: 52px !important;
    min-width: 52px !important; min-height: 52px !important;
    padding: 0 !important; margin: 0 !important; opacity: 0;
    border: none !important; background: transparent !important;
    border-radius: 50% !important; transform: translate(-50%, -50%); cursor: pointer;
}
.ds-base-hit--2 { left: 50%;   top: 16.7%; }
.ds-base-hit--1 { left: 83.3%; top: 50%; }
.ds-base-hit--3 { left: 16.7%; top: 50%; }
.ds-base-hit:focus-visible {
    opacity: 1; background: rgba(20,32,60,0.06) !important;
    outline: 3px solid #c8102e; outline-offset: -3px;
}

/* ===== 중: 상황 조작 — 이닝/스코어 스코어보드 + 스테퍼 ===== */
.ds-scoreboard {
    display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    background: #14203c; border-radius: 12px; padding: 12px 18px; margin: 6px 0 10px;
}
.ds-scoreboard .ds-sb-inning, .ds-scoreboard .ds-sb-score { display: flex; align-items: baseline; gap: 6px; }
.ds-scoreboard .ds-sb-num {
    font-family: 'Share Tech Mono', monospace; font-size: 26px; font-weight: 800; color: #ffffff;
}
.ds-scoreboard .ds-sb-arrow { color: #c8102e; font-size: 15px; font-weight: 800; }
.ds-scoreboard .ds-sb-unit { font-size: 14px; color: #e6e1d3; }
.ds-scoreboard .ds-sb-colon { color: #c8102e; font-size: 22px; font-weight: 800; }
.ds-steprow { gap: 8px !important; align-items: center !important; flex-wrap: wrap !important; }
.ds-step-btn { min-width: 44px !important; padding: 0 12px !important; flex: 0 1 auto !important; }

/* ===== 세그먼트 컨트롤 (gr.Radio를 목업의 세그먼트 버튼처럼) ===== */
.ds-seg {
    border: 1px solid #e6e1d3 !important; border-radius: 8px !important;
    background: #f7f5ef !important; padding: 4px !important;
}
.ds-seg .wrap { display: flex !important; gap: 4px !important; flex-wrap: wrap !important; }
.ds-seg .wrap label {
    flex: 1 1 auto; min-height: 44px; display: flex !important; align-items: center; justify-content: center;
    border: 1.5px solid #14203c !important; border-radius: 6px !important;
    background: transparent !important; padding: 0 14px !important; cursor: pointer;
}
.ds-seg .wrap label span { color: #14203c !important; font-weight: 800 !important; }
.ds-seg .wrap label:has(input:checked) { background: #c8102e !important; border-color: #c8102e !important; }
.ds-seg .wrap label:has(input:checked) span { color: #ffffff !important; }
/* 라디오 입력은 시각적으로만 숨기고 포커스는 유지한다 (키보드 이동 보존) */
.ds-seg .wrap input[type="radio"] {
    position: absolute !important; opacity: 0 !important; width: 1px !important; height: 1px !important;
    margin: 0 !important; pointer-events: none;
}
.ds-seg .wrap label:has(input:focus-visible) { outline: 3px solid #c8102e; outline-offset: 2px; }
.ds-seg--wide { width: 100% !important; }

/* ===== 우: 결과 패널 ===== */
.ds-situation {
    background: #f7f5ef; border: 1px solid #e6e1d3; border-radius: 12px; padding: 10px 12px;
    font-size: 13.5px; color: #6b6555; margin: 0 0 12px; word-break: keep-all;
}
.ds-situation b { color: #14203c; font-weight: 800; }
.ds-sec { margin-top: 18px; }
.ds-sec .ds-sec__t { display: block; font-size: 13px; font-weight: 900; color: #14203c; margin-bottom: 8px; }

/* ===== STRIKE ZONE BOARD 카드 (내부 SVG 히트맵 자체 색상은 별도 보정) ===== */
.ds-zone-card {
    background: #ffffff;
    border: 1px solid #e6e1d3; border-radius: 16px; padding: 18px 20px 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 6px 18px rgba(0,0,0,0.05);
}
.ds-zone-header { text-align: center; letter-spacing: 0.06em; font-weight: 800; }
.ds-zone-header-en { color: #c8102e; font-size: 20px; }
.ds-zone-header-sep { color: #9e9e9e; margin: 0 10px; font-weight: 400; }
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
.ds-zone-legend-label { font-size: 11px; color: #9e9e9e; }
.ds-zone-caption { text-align: center; color: #14203c; font-weight: 700; font-size: 15px; margin-top: 10px; }
.ds-zone-empty { text-align: center; }
.ds-zone-empty .ds-zone-caption { color: #6b6555; font-weight: 600; font-size: 14px; padding: 22px 6px 8px; }

/* ===== 분석 완료/진행 상태 표시 ===== */
.ds-status {
    text-align: center; font-weight: 700; font-size: 14.5px; padding: 10px 14px;
    border-radius: 10px; margin: 6px 0 0 0;
}
.ds-status-done { background: rgba(31,138,76,0.08); color: #1f8a4c; border: 1px solid rgba(31,138,76,0.3); }
.ds-status-pending { background: rgba(184,134,11,0.08); color: #b8860b; border: 1px solid rgba(184,134,11,0.3); }

/* ===== 접히는 섹션 (코칭 리포트 / Instant Scout Q&A) ===== */
.ds-report-accordion {
    border: 1px solid #e6e1d3 !important; border-radius: 16px !important; background: #ffffff !important;
    margin: 12px 0 0 0 !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 6px 18px rgba(0,0,0,0.05) !important;
}
.ds-report-accordion > .label-wrap { padding: 14px 18px !important; min-height: 52px !important; }
.ds-report-accordion > .label-wrap span { font-weight: 800 !important; color: #14203c !important; font-size: 16px !important; }
.ds-report-md { padding: 4px 16px 16px !important; }
.ds-report-md h1 { display: none; } /* "⚾ DiamondScout AI 전력분석 리포트" 대제목은 화면에서는 중복이라 숨김 */
.ds-report-md h2 {
    color: #c8102e !important; font-size: 18px !important; margin: 18px 0 6px !important;
    border-bottom: 2px solid #e6e1d3; padding-bottom: 6px;
}
.ds-report-md h3, .ds-report-md h4 {
    color: #14203c !important; font-size: 15.5px !important; margin: 16px 0 6px !important;
}
.ds-report-md p, .ds-report-md li { color: #6b6555 !important; font-size: 14.5px !important; line-height: 1.65 !important; }
.ds-report-md strong { color: #14203c !important; }
.ds-report-md blockquote {
    border-left: 3px solid #c8102e !important; background: rgba(200,16,46,0.05) !important;
    padding: 8px 12px !important; border-radius: 0 6px 6px 0 !important; margin: 8px 0 !important;
}
.ds-report-md em { color: #6b6555; }

/* ===== PDF 리포트 버튼 / 다운로드 박스 ===== */
.ds-btn-pdf { font-size: 15px !important; }
/* Gradio가 버튼을 감싸는 .styler 래퍼에 자체 배경(#e6e1d3)을 깔아서, 버튼 자체를
   transparent로 둬도 뒤에서 베이지색이 비쳐 보였다. 래퍼 배경을 투명화한다.
   (Gradio 6.19.0 기준, 버전 업그레이드 시 DOM 구조 변경 여부 재확인 필요) */
.styler:has(> .ds-btn-pdf) { background: transparent !important; }
.ds-pdf-file { margin-top: 8px !important; }
.ds-pdf-file .upload-container, .ds-pdf-file .empty { min-height: unset !important; padding: 0 !important; }
.ds-pdf-file button.reset-button, .ds-pdf-file .icon-buttons { display: none !important; }
.ds-pdf-file a, .ds-pdf-file .file-name, .ds-pdf-file [data-testid="file"] {
    background: #f7f5ef !important; border: 1.5px solid #14203c !important; border-radius: 10px !important;
    padding: 10px 14px !important; font-weight: 700 !important; color: #14203c !important;
}

/* ===== Instant Scout Q&A — 실제 메신저처럼 보이는 채팅 UI ===== */
.ds-qa-chips { flex-wrap: wrap !important; gap: 8px !important; margin-bottom: 10px !important; }
.ds-qa-chips button {
    background: #f7f5ef !important; color: #14203c !important; border: 1.5px solid #e6e1d3 !important;
    border-radius: 999px !important; font-size: 13px !important; font-weight: 600 !important;
    padding: 10px 14px !important; min-height: 44px !important; box-shadow: none !important;
    min-width: unset !important; flex: 0 0 auto !important;
}
.ds-qa-chips button:hover { border-color: #c8102e !important; color: #c8102e !important; }
.ds-chatbot { border-radius: 14px !important; border: 1px solid #e6e1d3 !important; overflow: hidden !important; }
.ds-chatbot .bubble-wrap, .ds-chatbot .panel-wrap { background: #f7f5ef !important; padding: 14px !important; }
.ds-chatbot .message-row { margin: 6px 0 !important; }
.ds-chatbot .avatar-container { display: none !important; }
/* 사용자 말풍선: 오른쪽 정렬 + 브랜드 네이비, 상대(봇) 말풍선: 왼쪽 정렬 + 흰 카드.
   실제 말풍선 배경은 .bubble.user-row(행 전체)가 아니라 그 안의 .message.user 요소에 칠해져 있다
   (Gradio 6.19 DOM 확인: <div class="user message">). 행에 배경을 줘도 안 보이는 이유였다. */
.ds-chatbot .message.user {
    background: #14203c !important; border: none !important; border-radius: 16px 16px 4px 16px !important;
    padding: 10px 14px !important; max-width: 82% !important;
}
.ds-chatbot .message.user, .ds-chatbot .message.user * { color: #ffffff !important; }
.ds-chatbot .message.bot {
    background: #ffffff !important; border: 1px solid #e6e1d3 !important; border-radius: 16px 16px 16px 4px !important;
    padding: 10px 14px !important; max-width: 82% !important;
    box-shadow: 0 1px 4px rgba(20,32,60,0.08) !important;
}
.ds-chatbot .message.bot, .ds-chatbot .message.bot * { color: #14203c !important; }
/* 입력 줄: 알약 모양 입력창 + 원형 전송 버튼, 메신저 하단 바처럼 */
.ds-qa-input-row {
    align-items: center !important; gap: 8px !important; margin-top: 10px !important;
    background: #f7f5ef !important; border: 1.5px solid #e6e1d3 !important; border-radius: 999px !important;
    padding: 4px 4px 4px 16px !important;
}
.ds-qa-input-row textarea, .ds-qa-input-row input {
    background: transparent !important; border: none !important; box-shadow: none !important;
    padding: 8px 0 !important;
}
.ds-btn-send {
    background: #c8102e !important; color: #ffffff !important; border: none !important;
    border-radius: 999px !important; min-width: 64px !important; min-height: 44px !important;
    font-weight: 700 !important; box-shadow: none !important;
}
.ds-btn-send:hover { background: #c8102e !important; filter: brightness(0.88); }

/* ===== 좌우 여백(카드 폭 밖) 장식 배경 — 야구 실밥 느낌의 대각선 패턴 + 은은한 포인트 컬러 ===== */
/* Gradio가 .gradio-container 폭을 뷰포트보다 1px 크게 계산해(375px에서 375.914px) 모바일에서
   가로로 1px 스크롤이 생겼다. clip은 hidden과 달리 스크롤 컨테이너를 만들지 않아
   모바일 존 컬럼의 position:sticky를 깨지 않는다. */
html { overflow-x: clip; }
body {
    background:
        radial-gradient(circle at 4% 15%, rgba(200,16,46,0.06) 0%, transparent 42%),
        radial-gradient(circle at 96% 80%, rgba(20,32,60,0.07) 0%, transparent 42%),
        repeating-linear-gradient(135deg, rgba(20,32,60,0.035) 0px, rgba(20,32,60,0.035) 2px, transparent 2px, transparent 26px),
        #f4f2ec !important;
    overflow-x: clip;
}

/* ===== 반응형 브레이크포인트 ===== */
/* 태블릿 — 2열, 결과는 아래 전폭 */
@media (max-width: 1023px) {
    .ds-console { grid-template-columns: 1fr 1fr !important; }
    .ds-col-result { grid-column: 1 / -1; }
}
/* 모바일 — 1열, 존은 상단 고정 */
@media (max-width: 767px) {
    .ds-console { grid-template-columns: 1fr !important; }
    .ds-col-zone   { order: 1; position: sticky; top: 0; z-index: 20; background: #f4f2ec; }
    .ds-col-result { order: 2; grid-column: auto; }
    .ds-col-matchup { order: 3; }
    .ds-card { padding: 14px 14px !important; }
    /* 터치 타겟 44px 확보 */
    .ds-lamp { width: 28px; height: 28px; margin-right: 10px; }
    .ds-lamp-group { min-height: 44px; display: flex; align-items: center; }
}
@media (prefers-reduced-motion: reduce) {
    * { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}

/* ============================================================================
   캔버스 스트라이크 존 씬 (Task 5Z)
   목업 output/mockups/dugout-console.html에서 이식. 목업은 var(--navy) 같은 토큰을
   썼지만 이 파일은 리터럴 색상을 쓰므로 같은 값으로 바꿔 넣었다.
   ============================================================================ */

/* 화면에는 안 보이지만 스크린리더는 읽는 텍스트 */
.ds-sr {
    position: absolute; width: 1px; height: 1px;
    padding: 0; margin: -1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}

/* 배경 래스터 → 캔버스 오버레이 → 클릭 레이어 순으로 쌓인다. 세 레이어가 같은 박스를
   채우므로 카메라만 맞으면 픽셀 단위로 정렬된다. aspect-ratio를 빼면 캔버스가 컬럼을
   넘쳐 타자가 잘린다 — 520x600 비율이 카메라 상수와 한 세트다. */
.ds-scene {
    position: relative;
    width: 100%;
    max-width: 520px;
    margin: 0 auto;
    aspect-ratio: 520 / 600;
    border-radius: 16px;
    overflow: hidden;
    border: 1px solid #e6e1d3;
    background: #f4f2ec;
}

.ds-scene__canvas {
    position: absolute; inset: 0;
    width: 100%; height: 100%;
    display: block;
    z-index: 1;
}

/* 존 위 직접 클릭(마우스 보조). 단일 면이라 탭 타깃 규칙과 무관하고,
   실제 조작·접근성은 아래 .ds-coursepad(44px 버튼 9개)가 담당한다. */
.ds-scene__cells { position: absolute; inset: 0; z-index: 2; cursor: crosshair; }

/* 코스 미리보기 패드 — 화면에 보이는 존과 같은 좌우 배열로 그린다.
   시점이 바뀌면 몸쪽/바깥쪽 열도 같이 뒤집힌다. */
.ds-coursepad {
    display: grid;
    grid-template-columns: repeat(3, minmax(44px, 1fr));
    gap: 4px;
    max-width: 216px;
    margin: 10px auto 0;
}

.ds-coursebtn {
    min-height: 44px;
    padding: 2px 1px;
    border: 1.5px solid #14203c;
    border-radius: 6px;
    background: transparent;
    color: #14203c;
    font-size: 10.5px;
    font-weight: 800;
    line-height: 1.25;
    cursor: pointer;
    transition: background .14s ease, color .14s ease;
}
.ds-coursebtn:hover { background: #14203c0f; }
.ds-coursebtn.is-on { background: #c8102e; border-color: #c8102e; color: #ffffff; }

.ds-coursepad__cap {
    grid-column: 1 / -1;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .1em;
    color: #6b6555;
    text-transform: uppercase;
    text-align: center;
    margin-bottom: 2px;
}

@media (max-width: 900px) {
    .ds-scene { max-width: 230px; }
}
"""
