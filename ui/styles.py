"""DiamondScout AI 전역 스타일.

2026-08-04 라이트 브로드캐스트 팔레트를 유지한다.
app.py에서 분리한 이유는 2292줄 모놀리스를 쪼개기 위함이며, 내용 변경은 없다.
"""

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Teko:wght@500;600;700&family=Share+Tech+Mono&display=swap');

:root {
    color-scheme: light;
}
.gradio-container {
    background: #f4f2ec !important;
    max-width: 1320px !important;
    margin: 0 auto !important;
    font-size: 17px !important;
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
.gradio-container h1 { color: #14203c; font-size: 34px !important; margin-bottom: 6px !important; }
.gradio-container h2 { color: #14203c; font-size: 25px !important; }
.gradio-container h3, .gradio-container h4 {
    color: #14203c; font-size: 21px !important; margin-top: 26px !important; margin-bottom: 12px !important;
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
    font-weight: 800; letter-spacing: 0.03em; font-size: 20px; padding: 2px 0 14px 12px;
    margin: 0 !important; border-left: 4px solid;
}
.ds-panel-title { color: #c8102e; border-color: #c8102e; }
.ds-board-title { color: #14203c; border-color: #14203c; }
.ds-qa-title { color: #14203c; border-color: #c8102e; }
/* ===== Instant Scout Q&A — 실제 메신저처럼 보이는 채팅 UI ===== */
.ds-qa-chips { flex-wrap: wrap !important; gap: 8px !important; margin-bottom: 10px !important; }
.ds-qa-chips button {
    background: #f7f5ef !important; color: #14203c !important; border: 1.5px solid #e6e1d3 !important;
    border-radius: 999px !important; font-size: 13px !important; font-weight: 600 !important;
    padding: 6px 14px !important; box-shadow: none !important; min-width: unset !important; flex: 0 0 auto !important;
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
    border-radius: 999px !important; min-width: 64px !important; font-weight: 700 !important;
    box-shadow: none !important;
}
.ds-btn-send:hover { background: #a00c24 !important; }
/* 전략 리포트 아코디언 — 본문은 기본 마크다운 검정 텍스트 대신 브랜드 컬러 위계를 따른다 */
.ds-report-accordion {
    border: 1px solid #e6e1d3 !important; border-radius: 12px !important; background: #fbfaf6 !important;
    margin: 8px 0 4px 0 !important;
}
.ds-report-accordion > .label-wrap { padding: 12px 16px !important; }
.ds-report-accordion > .label-wrap span { font-weight: 700 !important; color: #14203c !important; font-size: 15px !important; }
.ds-report-md { padding: 4px 16px 16px !important; }
.ds-report-md h1 { display: none; } /* "⚾ DiamondScout AI 전력분석 리포트" 대제목은 화면에서는 중복이라 숨김 */
.ds-report-md h2 {
    color: #c8102e !important; font-size: 18px !important; margin: 18px 0 6px !important;
    border-bottom: 2px solid #f0dede; padding-bottom: 6px;
}
.ds-report-md h3, .ds-report-md h4 {
    color: #14203c !important; font-size: 15.5px !important; margin: 16px 0 6px !important;
}
.ds-report-md p, .ds-report-md li { color: #4a4638 !important; font-size: 14.5px !important; line-height: 1.65 !important; }
.ds-report-md strong { color: #14203c !important; }
.ds-report-md blockquote {
    border-left: 3px solid #c8102e !important; background: rgba(200,16,46,0.05) !important;
    padding: 8px 12px !important; border-radius: 0 6px 6px 0 !important; margin: 8px 0 !important;
}
.ds-report-md em { color: #8a8367; }
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
/* ===== 주자 상황 다이아몬드 — 실제 야구장 항공샷처럼 흙(basepath) 테두리 + 잔디 인필드 +
   마운드를 그리고, 체크박스를 루 위치의 작은 다이아몬드 마커로 배치한다 ===== */
.ds-diamond-wrap {
    justify-content: center !important; padding: 56px 50px 40px !important; overflow: visible !important;
    background: #eef2e6 !important;
    border: 1px solid #d2e2ba !important; border-radius: 20px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.6) !important;
}
.ds-diamond { position: relative !important; width: 320px; height: 320px; margin: 0 auto; overflow: visible !important; }
/* 흙(basepath) 테두리 다이아몬드 — border가 흙색, 안쪽 fill이 잔디색 */
.ds-diamond::before {
    content: ""; position: absolute; top: 50%; left: 50%; width: 160px; height: 160px; z-index: 0;
    background: linear-gradient(135deg, #8fb673 0%, #7fa668 100%);
    border: 24px solid #c89f6c; border-radius: 10px; transform: translate(-50%, -50%) rotate(45deg);
    box-shadow: inset 0 0 0 3px rgba(169,127,78,0.6), 0 6px 16px rgba(70,45,15,0.15);
}
.ds-diamond::after {
    content: "HOME"; position: absolute; top: 102.8%; left: 50%; transform: translateX(-50%); z-index: 1;
    font-family: 'Share Tech Mono', monospace; font-size: 10px; color: #7c8a63; letter-spacing: 0.08em;
}
/* Gradio가 절대배치 자식들을 감싸는 .form 래퍼의 auto-height가 거의 0으로 붕괴되면서
   overflow:hidden(기본값)에 베이스가 잘려 보이는 문제 — 명시적으로 visible 처리 */
.ds-diamond .form { overflow: visible !important; height: auto !important; }
/* 마운드 — .form이 체크박스 3개를 감싸는 실제 DOM 요소라 여기 붙여야 다이아몬드 중앙에 정확히 놓인다 */
.ds-diamond .form::before {
    content: ""; position: absolute; top: 50%; left: 50%; width: 34px; height: 34px; z-index: 0;
    background: radial-gradient(circle at 35% 32%, #d3ab7d, #a97f4e); border-radius: 50%;
    box-shadow: 0 3px 6px rgba(40,25,8,0.35); transform: translate(-50%, -50%);
}
.ds-base-card {
    position: absolute !important; width: 96px !important; background: transparent !important;
    border: none !important; padding: 0 !important; box-shadow: none !important; z-index: 2;
    overflow: visible !important; height: auto !important; transform: translate(-50%, -50%);
}
/* 2루=인필드 상단 꼭짓점 / 3루=좌측 꼭짓점 / 1루=우측 꼭짓점보다 한 칸 더 바깥으로 띄워
   흙/잔디 필드 테두리와 겹치지 않게 한다 */
.ds-base-card.ds-base-2b { top: -4.7%; left: 50%; }
.ds-base-card.ds-base-3b { top: 50%; left: -4.7%; }
.ds-base-card.ds-base-1b { top: 50%; left: 104.7%; }
.ds-base-card label {
    display: flex !important; flex-direction: column-reverse !important; align-items: center !important; gap: 8px;
    cursor: pointer;
}
.ds-base-card label span {
    font-size: 14px !important; font-weight: 800; color: #4a4638; letter-spacing: 0.02em;
    transition: all 0.15s ease;
}
.ds-base-card input[type=checkbox] {
    appearance: none; -webkit-appearance: none; width: 40px !important; height: 40px !important; margin: 0 !important;
    background: linear-gradient(145deg, #fffdf8, #ece6d4); border: 2.5px solid #ffffff; border-radius: 7px;
    transform: rotate(45deg); cursor: pointer; transition: all 0.18s cubic-bezier(0.34, 1.56, 0.64, 1);
    box-shadow: 0 3px 8px rgba(40,30,10,0.25), inset 0 -2px 3px rgba(0,0,0,0.06);
}
.ds-base-card input[type=checkbox]:hover { border-color: #c8102e; transform: rotate(45deg) scale(1.1); }
/* 체크 시 확실히 티나게: 확대 + 진한 레드 + 이중 글로우 링 */
.ds-base-card input[type=checkbox]:checked {
    background: linear-gradient(145deg, #ff3b57, #b3081f) !important; border-color: #ffffff !important;
    border-width: 3px !important; transform: rotate(45deg) scale(1.4);
    box-shadow: 0 0 0 4px rgba(255,255,255,0.9), 0 0 0 9px rgba(200,16,46,0.35),
                0 0 18px 4px rgba(200,16,46,0.5), 0 4px 12px rgba(168,13,36,0.55);
}
.ds-base-card:has(input:checked) label span {
    color: #ffffff; background: #c8102e; padding: 2px 10px; border-radius: 6px;
    box-shadow: 0 2px 6px rgba(168,13,36,0.4);
}
/* 버튼: Primary(레드)/Ghost(아웃라인) 2종만 사용 */
.gradio-container button { font-size: 16.5px !important; border-radius: 8px !important; }
.ds-btn-analyze {
    background: #c8102e !important; color: #ffffff !important; border: none !important;
    font-weight: 800 !important; box-shadow: 0 4px 10px rgba(200,16,46,0.28) !important;
}
.ds-btn-analyze:hover { box-shadow: 0 6px 16px rgba(200,16,46,0.4) !important; transform: translateY(-1px); }
/* "다음" 버튼은 "분석 실행"(레드)과 시각적으로 구분되도록 네이비로 분리 */
.ds-btn-next {
    background: #14203c !important; color: #ffffff !important; border: none !important;
    font-weight: 800 !important; box-shadow: 0 4px 10px rgba(20,32,60,0.28) !important;
}
.ds-btn-next:hover { box-shadow: 0 6px 16px rgba(20,32,60,0.4) !important; transform: translateY(-1px); }
/* STEP 4(마지막 스텝)에서는 '다음' 버튼을 숨긴다. Python에서 두 버튼의 visible=을 함께 토글하면
   간헐적으로 갱신이 누락되는 문제가 있어(위 _analyze_btn_update 설명 참고), '분석 실행'이 보일 때
   CSS 형제 선택자로 '다음'을 숨기는 방식으로 대체했다. */
.ds-btn-analyze:not(.hidden) ~ .ds-btn-next { display: none !important; }
.ds-btn-prev, .ds-btn-reset {
    background: transparent !important; color: #6b6555 !important; border: 1.5px solid #ddd8ca !important;
    box-shadow: none !important; font-weight: 700 !important;
}
.ds-btn-prev:hover, .ds-btn-reset:hover { border-color: #14203c !important; color: #14203c !important; }
.ds-btn-reset { margin-bottom: 10px !important; }
/* 이전/다음/분석 실행 버튼은 한 줄(Row)에 나란히 놓이므로 높이를 강제로 맞춘다.
   .ds-btn-analyze는 Gradio variant="primary" 기본 패딩이 달라 그대로 두면 더 커 보였다. */
.ds-btn-prev, .ds-btn-next, .ds-btn-analyze {
    padding: 12px 18px !important; min-height: 46px !important; box-sizing: border-box !important;
    margin-top: 0 !important;
}
.ds-btn-pdf {
    background: transparent !important; color: #14203c !important; border: 1.5px solid #14203c !important;
    font-size: 15px !important; padding: 11px !important; font-weight: 700 !important; box-shadow: none !important;
}
.ds-btn-pdf:hover { background: #14203c !important; color: #ffffff !important; }
/* Gradio가 버튼을 감싸는 .styler 래퍼에 자체 배경(#e6e1d3)을 깔아서, 버튼 자체를
   transparent로 둬도 뒤에서 베이지색이 비쳐 보였다. 래퍼 배경을 투명화해 카드(.ds-board)의
   흰 배경이 그대로 보이게 한다. (Gradio 6.19.0 기준, 버전 업그레이드 시 DOM 구조 변경 여부 재확인 필요) */
.styler:has(> .ds-btn-pdf) { background: transparent !important; }
/* PDF 다운로드 박스: 기본 Gradio File은 큰 드롭존으로 보여 어색하다. 생성 후에만 노출되므로
   얇은 링크형 카드로 축소한다. */
.ds-pdf-file { margin-top: 8px !important; }
.ds-pdf-file .upload-container, .ds-pdf-file .empty { min-height: unset !important; padding: 0 !important; }
.ds-pdf-file button.reset-button, .ds-pdf-file .icon-buttons { display: none !important; }
.ds-pdf-file a, .ds-pdf-file .file-name, .ds-pdf-file [data-testid="file"] {
    background: #f7f5ef !important; border: 1.5px solid #14203c !important; border-radius: 10px !important;
    padding: 10px 14px !important; font-weight: 700 !important; color: #14203c !important;
}
/* 입력 컴포넌트 라벨/텍스트 가독성 */
.gradio-container label span, .gradio-container .label-wrap span { font-size: 16.5px !important; }
/* STRIKE ZONE BOARD 카드 (내부 SVG 히트맵 자체 색상은 별도 보정) */
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
/* 스텝 전환 애니메이션 — Gradio가 비활성 스텝에 인라인 style="display: none"을 걸었다가
   빼는 방식으로 전환하므로, display:none에서 벗어날 때마다 애니메이션이 처음부터 다시
   재생된다(별도 JS 트리거 불필요). */
.ds-wizard-card:not([style*="display: none"]) {
    animation: ds-step-in 0.32s ease;
}
@keyframes ds-step-in {
    from { opacity: 0; transform: translateX(14px); }
    to { opacity: 1; transform: translateX(0); }
}
@media (prefers-reduced-motion: reduce) {
    .ds-wizard-card { animation: none !important; }
}
/* 스텝 전환은 위쪽 진행 트랙으로만 하므로 gr.Tabs 기본 헤더는 숨긴다
   (Gradio 6.19.0 기준, 버전 업그레이드 시 DOM 구조 변경 여부 재확인 필요) */
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
/* 색상만으로 완료 상태를 구분하면 색각 이상 사용자가 인지하기 어려우므로 체크마크를 덧붙인다 */
.ds-step-done::after { content: " \\2713"; }
.ds-step-now {
    border-bottom-color: #14203c !important; color: #14203c !important;
    background: #f7f5ef !important; border-radius: 8px 8px 0 0 !important;
}
.ds-step-next { border-bottom-color: #ddd8ca !important; color: #b8ae94 !important; }

/* ===== 현재 매치업 요약 패널 (데스크톱 전용) — 이름만 크게 보여준다 ===== */
.ds-matchup-panel {
    display: none;
    background: #14203c !important; color: #ffffff !important;
    border-radius: 16px !important; padding: 26px !important;
    flex-direction: column; justify-content: center; align-items: center; text-align: center;
}
.ds-matchup-panel .ds-mp-title {
    font-size: 13px; font-weight: 700; letter-spacing: 0.08em; color: #b9c3dd; text-transform: uppercase;
    border-bottom: 1px solid rgba(255,255,255,0.15); padding-bottom: 12px; margin-bottom: 16px; width: 100%;
}
.ds-matchup-panel .ds-mp-role {
    font-size: 13px; font-weight: 700; letter-spacing: 0.06em; color: #b9c3dd; text-transform: uppercase; margin-top: 16px;
}
.ds-matchup-panel .ds-mp-name { font-size: 25px; font-weight: 800; color: #ffffff; margin-top: 4px; }
.ds-matchup-panel .ds-mp-vs {
    color: #c8102e; font-weight: 800; font-size: 15px; letter-spacing: 0.1em; margin: 18px 0 2px;
}

/* ===== 결과 화면 코칭 보드 레이아웃 ===== */
/* 코칭 보드 재정리: 추천 구종/존 보드는 전체 폭 하이라이트, 위험도·상대 패턴은 보조 2열 정보로 분리 */
.ds-quick-row { display: grid !important; grid-template-columns: 1fr 1fr; gap: 14px; margin: 10px 0; }
@media (max-width: 639px) { .ds-quick-row { grid-template-columns: 1fr; } }
.ds-board-section-title { margin: 18px 0 8px 0 !important; }
.ds-board-section-title h4 {
    font-size: 15px !important; font-weight: 800 !important; color: #14203c !important;
    letter-spacing: 0.02em; border-left: 4px solid #c8102e; padding-left: 10px; margin: 0 !important;
}

/* ===== 카운트/이닝 시각화 스코어보드 (STEP 2, 원시 입력값을 읽기 쉽게 재표시) ===== */
.ds-count-board {
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
    background: #14203c; border-radius: 12px; padding: 14px 18px; margin: 8px 0 16px 0;
}
.ds-cb-item { display: flex; align-items: center; gap: 6px; }
.ds-cb-label { font-family: 'Share Tech Mono', monospace; color: #b9c3dd; font-weight: 700; font-size: 14px; margin-right: 2px; }
.ds-cb-dot { width: 16px; height: 16px; border-radius: 50%; background: rgba(255,255,255,0.15); display: inline-block; }
.ds-cb-dot.on { background: var(--c); }
.ds-cb-inning {
    margin-left: auto; font-family: 'Share Tech Mono', monospace; color: #ffffff; font-weight: 800; font-size: 17px;
}

/* ===== 반응형 브레이크포인트 ===== */
@media (min-width: 1280px) {
    .ds-matchup-panel { display: flex; }
    .ds-wizard-row { align-items: stretch !important; }
}
@media (max-width: 639px) {
    /* flex:1 인 버튼은 기본 min-width:auto 때문에 텍스트 폭 밑으로 줄어들지 않아, 4개를 한 줄에
       나눠 담을 좁은 화면에서 뒤쪽 스텝(3/4)이 트랙 밖으로 밀려나 보이지 않는 문제가 있었다.
       min-width:0으로 강제 축소를 허용하고, 넘치는 텍스트는 말줄임표로 처리한다. */
    .ds-step-dot {
        font-size: 11.5px !important; padding: 8px 3px !important; letter-spacing: -0.01em !important;
        min-width: 0 !important; overflow: hidden !important; text-overflow: ellipsis !important;
        white-space: nowrap !important;
    }
    .ds-panel, .ds-board, .ds-qa-panel { padding: 16px 14px !important; }
}

/* ===== 좌우 여백(카드 폭 밖) 장식 배경 — 야구 실밥 느낌의 대각선 패턴 + 은은한 포인트 컬러 ===== */
body {
    background:
        radial-gradient(circle at 4% 15%, rgba(200,16,46,0.06) 0%, transparent 42%),
        radial-gradient(circle at 96% 80%, rgba(20,32,60,0.07) 0%, transparent 42%),
        repeating-linear-gradient(135deg, rgba(20,32,60,0.035) 0px, rgba(20,32,60,0.035) 2px, transparent 2px, transparent 26px),
        #f4f2ec !important;
}

/* ===== 랜딩 화면 ===== */
.ds-landing-hero { text-align: center; padding: 34px 20px 10px; }
.ds-landing-badge {
    display: inline-block; background: rgba(200,16,46,0.08); color: #c8102e; border: 1px solid rgba(200,16,46,0.3);
    border-radius: 999px; font-size: 13px; font-weight: 700; padding: 5px 14px; letter-spacing: 0.05em;
}
.ds-landing-title { font-size: 40px; font-weight: 800; color: #14203c; margin: 14px 0 8px; }
.ds-landing-sub { font-size: 18px; color: #4b463c; max-width: 620px; margin: 0 auto; line-height: 1.6; }
.ds-landing-features { gap: 16px !important; margin: 24px 0 !important; }
.ds-landing-feature {
    background: #ffffff; border: 1px solid #e6e1d3; border-radius: 14px; padding: 22px 20px; height: 100%;
    box-shadow: 0 4px 14px rgba(20,32,60,0.06);
}
.ds-lf-title { font-family: 'Teko', sans-serif; font-size: 21px; font-weight: 800; color: #c8102e; margin-bottom: 8px; }
.ds-lf-desc { font-size: 15px; color: #4b463c; line-height: 1.5; }
.ds-landing-start { display: block !important; margin: 8px auto 30px !important; min-width: 220px; font-size: 19px !important; }
"""
