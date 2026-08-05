# 트러블슈팅 기록 (DiamondScout_AI)

> 이 프로젝트 전용 트러블슈팅 로그. 다른 프로젝트 기록은 `~/Project/TROUBLESHOOTING.md`(전역 공용 파일)에 있다.
> 포트폴리오·면접 자료로 그대로 쓸 수 있게, **문제 → 원인 → 해결 → 추후 관리**를 항상 채운다.

## 작성 규칙

1. 문제를 해결한 직후에 쓴다.
2. 재현되지 않은 추측은 원인에 쓰지 않는다. 확인한 것과 추정한 것을 구분한다.
3. 실패한 시도도 남긴다.
4. 새 항목은 인덱스 표 맨 위에 추가하고(최신순), 본문은 아래에 이어 붙인다.
5. ID는 `TS-001`부터 순번.
6. 로그·에러 메시지는 원문 그대로 코드블록에 넣는다.
7. 비밀값은 `<REDACTED>`로 치환한다.

---

## 인덱스

| ID | 날짜 | 영역 | 문제 | 심각도 | 상태 |
|---|---|---|---|---|---|
| TS-003 | 2026-08-05 | FE | STEP4 "분석 실행" 버튼이 새로고침 직후 첫 방문에서 100% 사라짐 — Gradio 컴포넌트의 "첫 visible= 전환" 렌더링 누락 | High | 해결됨 |
| TS-002 | 2026-08-04 | FE | 마운드 장식용 `position:relative`가 절대배치 베이스 3개의 기준 조상을 바꿔 한 점에 뭉쳐 보임 | Medium | 해결됨 |
| TS-001 | 2026-08-04 | FE | 절대배치 자식만 있는 Gradio `.form` wrapper의 auto-height 붕괴로 베이스 마커 하단이 잘림 | Medium | 해결됨 |

**영역**: `FE` / `BE` / `DB` / `Infra` / `ML` / `Build` / `Test`
**심각도**: `Critical` / `High` / `Medium` / `Low`
**상태**: `해결됨` / `우회 적용` / `미해결` / `재발`

---

## 기록

## TS-003 · STEP4 "분석 실행" 버튼이 새로고침 직후 첫 방문에서 100% 사라짐 — Gradio 컴포넌트의 "첫 visible= 전환" 렌더링 누락

| | |
|---|---|
| **날짜** | 2026-08-05 |
| **영역** | FE |
| **심각도** | High |
| **상태** | 해결됨 |
| **소요 시간** | 정확히 측정 안 함 — 같은 대화 안에서 두 차례 재조사(1차 수정 후 오판, 사용자 재보고로 재조사) |

### 증상
STEP1→STEP4로 마법사를 진행하면 STEP4에서 "분석 실행" 버튼이 안 보이고, 근처의 "다시 분석"(리셋) 버튼만 보였다. 사용자가 "분석 버튼 어디갔니 STEP4에서 분석버튼 없어지고 다시분석 이런게 뜨는데"라고 보고.

### 재현 조건
- 환경: Gradio 6.19.0, `p_analyze_btn`/`b_analyze_btn`은 Python에서 `visible=False`로 선언되고, STEP4 진입 시 `_analyze_btn_update()`가 `gr.Button(visible=True)`를 반환하는 구조
- 재현 절차: 페이지를 **새로고침한 직후**, STEP1 → "다음" ×3 → STEP4 도달
- 재현율: 새로고침 후 첫 진입 시 **100%**. 같은 세션에서 STEP4를 두 번째 이후로 재방문하면 **항상 정상**

### 원인
- **표면**: "분석 실행" 버튼의 `visible` 값이 STEP4 진입 이벤트에서 `True`로 바뀌었는데도 화면(`display`)이 갱신되지 않음
- **근본(확인된 범위)**: 컴포넌트가 Python 쪽 **정적 초기값**(`visible=False`)에서 한 번도 실제 이벤트를 거치지 않은 상태로 있다가, 그 값이 처음으로 바뀌는 **"첫 번째 live 전환"**에서만 렌더링이 누락된다. 같은 컴포넌트의 **두 번째 이후 전환은 예외 없이 정상**이었다. Gradio/Svelte 내부의 정확한 메커니즘(왜 첫 전환만 실패하는지)까지는 소스 레벨로 파고들지 않았으므로 "확인된 것"은 재현 패턴이고, 내부 동작 원리 자체는 추정으로 남긴다.
- **확인 방법**: `mcp__claude-in-chrome__javascript_tool`로 매번 **새 페이지 로드**부터 시작해 "시작하기" → "다음" ×3을 프로그래밍적으로 클릭한 뒤 `getComputedStyle(button).display`를 측정하는 결정론적 스크립트를 작성. 700ms~2s 등 지연 시간을 바꿔가며(레이스 컨디션 가설 배제), 총 여러 차례 반복해 "새로고침 후 첫 전환은 항상 실패, 두 번째 전환부터는 항상 성공"이라는 패턴을 확정했다.

### 시도했지만 안 된 것
| 시도 | 결과 | 왜 안 됐는가 |
|---|---|---|
| "다음"/"분석 실행" 두 버튼을 같은 이벤트 출력에서 동시에 `visible=` 토글 (`_next_btn_update` 추가) | 브라우저 수동 테스트 일부에서는 동작하는 것처럼 보였으나 실제로는 여전히 실패 | 한 이벤트에서 여러 컴포넌트의 `visible=`을 동시에 토글하면 두 번째 전환부터 간헐적으로 갱신이 누락되는 기존에 알려진 Gradio 문제(카드 전환에 `gr.Tabs(selected=)`를 쓰게 된 이전 세션의 원인과 동일 계열)와 겹쳐, 증상을 오히려 더 불안정하게 만듦 |
| 위 수정 후 "완료"로 보고 | 사용자가 실사용에서 동일 증상 재보고 | 브라우저 자동화에서 발생한 실패를 "stale element reference(참조가 오래돼 갱신 안 됨)" 탓으로 성급히 결론짓고, 실제 앱 버그 가능성을 배제한 채 검증을 끝냄 — 재현 스크립트를 결정론적으로 다시 만들고 나서야 오판이었음을 확인 |

### 해결
두 부분으로 나눠 해결:
1. **"다음" 버튼**: Python 쪽 `visible=` 토글을 완전히 제거. 대신 "분석 실행" 버튼이 보일 때 CSS 형제 선택자로 "다음" 버튼을 숨긴다 — 애초에 한 이벤트에서 두 컴포넌트를 동시에 토글하는 상황 자체를 없앰.
   ```css
   .ds-btn-analyze:not(.hidden) ~ .ds-btn-next { display: none !important; }
   ```
2. **"분석 실행" 버튼(priming 패턴)**: 초기값을 `visible=False` 대신 `visible=True`로 선언(이 버튼은 `main_tabs`라는 이미 `visible=False`인 조상 안에 있어 사용자에게 깜빡임 없음). 그 대신 `demo.load()`에서 실제 이벤트로 한 번 `visible=False`로 되돌린다. 이렇게 하면 사용자가 실제로 STEP4에 도달해 마주치는 `False→True` 전환은 항상 "두 번째 live 전환"이 되어 안정적으로 렌더링된다.
   ```python
   p_analyze_btn = gr.Button("분석 실행", variant="primary", elem_classes=["ds-btn-analyze"], visible=True)
   ...
   demo.load(
       fn=lambda: (gr.Button(visible=False), gr.Button(visible=False)),
       outputs=[p_analyze_btn, b_analyze_btn],
   )
   ```

### 검증
새로고침마다 새 페이지 로드부터 시작하는 결정론적 JS 테스트를 반복 실행(지연 시간을 700ms/300ms 등으로 바꿔가며, 투수 모드 3회 + 타자 모드 1회 총 4회). 매번 STEP4에서 `getComputedStyle()`로 `analyzeDisplay: "flex"`, `nextDisplay: "none"` 확인 — 수정 전엔 100% 재현되던 실패가 수정 후 4/4 전부 통과. 이후 대화(PDF 다운로드 버튼 UI 개선)에서도 같은 패턴을 신규 컴포넌트(`p_pdf_file_output`)에 선제 적용해 추가 검증했다.

### 추후 관리
- **재발 방지**: 페이지 로드 시점엔 숨겨져 있다가 나중에 사용자 액션으로 나타나야 하는 컴포넌트를 새로 추가할 때는, 기본값으로 이 priming 패턴(초기값 `visible=True` + `demo.load()`에서 실제 이벤트로 `False` 전환)을 먼저 검토하기로 함.
- **모니터링**: 없음
- **남은 리스크**: Gradio 버전을 올릴 때 이 버그(및 회피용 priming 패턴)가 여전히 필요한지 재검증 필요 — 프레임워크가 고치면 이 우회 코드는 불필요한 복잡도로 남는다.
- **후속 작업**: 없음

### 배운 점
자동화 테스트의 실패를 "테스트 도구 자체의 아티팩트"로 성급히 결론짓지 않는다 — 사용자가 실사용에서 같은 증상을 다시 보고하면 그 가설은 즉시 폐기하고 처음부터 재조사해야 한다. 이번에는 좌표/참조(ref) 기반 클릭 대신 텍스트 매칭 클릭 + `getComputedStyle()` 검증으로 만든 결정론적 재현 스크립트가, 겉보기엔 "간헐적"으로 보이던 버그를 "새로고침 후 첫 전환은 항상 실패"라는 명확한 패턴으로 확정하는 데 결정적이었다.

### 참고
- 없음 (Gradio/Svelte 내부 렌더링 문제, 공식 이슈 트래커까지는 확인하지 않음)

---

## TS-002 · 마운드 장식용 `position:relative`가 절대배치 베이스 3개의 기준 조상을 바꿔 한 점에 뭉쳐 보임

| | |
|---|---|
| **날짜** | 2026-08-04 |
| **영역** | FE |
| **심각도** | Medium |
| **상태** | 해결됨 |
| **소요 시간** | 약 15분 |

### 증상
TS-001을 고친 직후, 다이아몬드 중앙에 마운드(투수판) 장식 원을 추가하자 2루·3루·1루 베이스 마커 3개가 전부 화면 위쪽 한 지점에 겹쳐 보였다. 각 마커는 `top: 12.1% / 50% / 87.9%`로 서로 다른 위치를 지정했는데도 시각적으로 완전히 같은 자리에 있었다.

### 재현 조건
- 환경: Gradio 6.19.0, `.ds-diamond`(position:relative, 320×320px) > `.form`(Gradio 자동 생성 wrapper) > `.ds-base-card`(체크박스 3개, position:absolute) 구조
- 재현 절차:
  1. 마운드 pseudo-element를 다이아몬드 정중앙에 그리려고 `.ds-diamond .form::before`를 추가
  2. `::before`가 올바르게 위치잡도록 `.ds-diamond .form { position: relative !important; }`를 같이 추가
  3. STEP 3 · 베이스 & 스코어 화면 진입
- 재현율: 항상

### 원인
- **표면**: `top` 값이 서로 다른 세 베이스 마커가 브라우저에서 동일한 좌표에 렌더링됨
- **근본**: `position:absolute` 요소의 `top/left` 퍼센트는 **가장 가까운 positioned 조상**(`position`이 static이 아닌 조상)을 기준으로 계산된다. 원래는 `.ds-base-card`의 positioned 조상이 `.ds-diamond`(320px)였는데, 마운드를 위해 `.form`에 `position: relative`를 추가하면서 `.ds-base-card`의 positioned 조상이 `.ds-diamond`에서 `.form` 자신으로 바뀌어버렸다. `.form`은 TS-001과 같은 이유(자식이 전부 absolute라 콘텐츠가 일반 흐름 높이에 기여하지 않음)로 auto-height가 거의 0에 가까워, `top: 50%` 같은 퍼센트 값이 사실상 0에 수렴해 세 마커가 한 점에 뭉쳤다.
- **확인 방법**: `mcp__claude-in-chrome__javascript_tool`로 `.ds-diamond`와 세 베이스 카드에 `getBoundingClientRect()`를 호출해 실측. `b2/b3/b1`의 `top`이 245.44px로 셋 다 정확히 동일하고, `.ds-diamond`의 실제 top(278.24px)과도 안 맞는 것을 확인해 "positioned 조상이 바뀌었다"는 가설을 세우고 검증했다.

### 시도했지만 안 된 것
| 시도 | 결과 | 왜 안 됐는가 |
|---|---|---|
| (없음) | — | `getBoundingClientRect()` 실측값 하나로 원인이 바로 드러나 다른 가설을 시도할 필요가 없었다 |

### 해결
`app.py`의 CUSTOM_CSS에서 `.ds-diamond .form { position: relative !important; }` 한 줄만 제거(overflow/height visible 처리는 유지). `.form`이 다시 `position:static`으로 돌아가면, 마운드 pseudo-element의 절대배치는 자동으로 그 다음 positioned 조상인 `.ds-diamond`를 기준으로 잡히므로 마운드 위치는 별도 조치 없이 그대로 유지된다.

```css
/* 수정 전 */
.ds-diamond .form { overflow: visible !important; height: auto !important; position: relative !important; }
/* 수정 후 */
.ds-diamond .form { overflow: visible !important; height: auto !important; }
```

### 검증
`getBoundingClientRect()`로 재측정 → `.ds-diamond`(top 538px, height 320px) 기준으로 `b3`/`b1`의 top이 664px로 서로 일치하고, 다이아몬드 수직 중앙(538+160=698)과 카드 중심(664+34=698)이 정확히 맞아떨어짐을 확인. `b2`는 489px로 다이아몬드 위쪽에 분리되어 있음도 함께 확인. 브라우저 스크린샷으로 시각 확인 병행.

### 추후 관리
- **재발 방지**: 없음(일회성 CSS 수정). 같은 컨테이너 안에 이미 절대배치로 좌표를 맞춘 요소가 있을 때, 장식용 pseudo-element 하나를 위해 중간 wrapper의 `position`을 바꾸는 CSS는 항상 "이 변경이 기존 절대배치 요소들의 기준점도 함께 바꾸는가"를 먼저 점검하기로 함.
- **모니터링**: 없음
- **남은 리스크**: 없음(근본 원인 제거로 해결, 우회 아님)
- **후속 작업**: 없음

### 배운 점
절대배치 요소의 `top/left` %는 "가장 가까운 positioned 조상"을 기준으로 계산된다는 CSS 기본 규칙을, 장식 요소 하나를 추가하며 무심코 잊었던 게 회귀의 원인이었다. 같은 컨테이너를 공유하는 다른 절대배치 요소가 있다면, `position` 값을 바꾸는 CSS 한 줄이 그 요소들의 기준 좌표계 전체를 바꿀 수 있다는 걸 항상 의심해야 한다.

### 참고
- MDN, Containing block (positioned 조상이 % 기준이 되는 규칙) — <https://developer.mozilla.org/en-US/docs/Web/CSS/Containing_block>

---

## TS-001 · 절대배치 자식만 있는 Gradio `.form` wrapper의 auto-height 붕괴로 베이스 마커 하단이 잘림

| | |
|---|---|
| **날짜** | 2026-08-04 |
| **영역** | FE |
| **심각도** | Medium |
| **상태** | 해결됨 |
| **소요 시간** | 약 20분 |

### 증상
야구 다이아몬드 모양으로 재배치한 주자 상황 UI(1루/2루/3루 체크박스를 `position:absolute`로 각 루 위치에 배치)에서, 세 베이스 아이콘 전부 아래쪽이 잘려 오각형처럼 보였다. 사용자가 스크린샷으로 "베이스 하단 다 잘려있잖아"라고 보고.

```
(사용자 제공 스크린샷 — 다이아몬드 모양 베이스의 하단 절반이 잘려 오각형처럼 보임)
```

### 재현 조건
- 환경: Gradio 6.19.0, 체크박스 3개(`elem_classes=["ds-base-card", ...]`)를 `gr.Column(elem_classes=["ds-diamond"])` 안에 넣고 CSS로 `position:absolute` 배치
- 재현 절차: STEP 3 · 베이스 & 스코어 화면 진입 → 베이스 마커 렌더링
- 재현율: 항상

### 원인
- **표면**: 흰색 다이아몬드 모양 베이스 아이콘의 아래쪽 절반가량이 잘려서 보임
- **근본**: Gradio가 체크박스 그룹을 감싸려고 자동 생성하는 `.form` div가 `.ds-diamond`와 `.ds-base-card` 사이에 끼어 있는데, 그 자식(`.ds-base-card`)이 전부 `position:absolute`라 일반 흐름(normal flow) 높이에 기여하지 않는다. 그 결과 `.form`의 auto-height가 거의 0(`height: 2px`)으로 붕괴하고, `.form`의 기본 `overflow: auto hidden` 때문에 2px를 넘는 모든 내용이 잘렸다.
- **확인 방법**: `mcp__claude-in-chrome__javascript_tool`로 `.ds-base-2b`부터 부모 체인을 타고 올라가며 `getComputedStyle()`을 dump. `.form.svelte-d5xbca` 요소가 `overflow: "auto hidden", height: "2px"`로 나오는 것을 확인해 클리핑 지점을 특정했다.

### 시도했지만 안 된 것
| 시도 | 결과 | 왜 안 됐는가 |
|---|---|---|
| `.ds-diamond`/`.ds-diamond-wrap`에 `overflow: visible !important` 적용 | 여전히 잘림 | 실제 클리핑 지점이 이 두 요소가 아니라 그 사이에 낀, 내가 만들지 않은 Gradio 자동 생성 `.form` wrapper였음 (DOM 체인을 끝까지 dump한 뒤에야 발견) |

### 해결
`app.py`의 CUSTOM_CSS에 다음 규칙 추가:

```css
.ds-diamond .form { overflow: visible !important; height: auto !important; }
```

### 검증
서버 재시작 후 브라우저에서 STEP 3 화면을 재확인. 베이스 3개의 다이아몬드 모양이 잘리지 않고 온전히 렌더링되는 것을 스크린샷으로 확인.

### 추후 관리
- **재발 방지**: 없음(일회성 CSS 수정). 이후 절대배치 자식을 쓰는 새 컴포넌트를 추가할 때는 같은 `.form` 붕괴 패턴을 먼저 의심하기로 함.
- **모니터링**: 없음
- **남은 리스크**: Gradio 버전이 올라가 `.form` wrapper의 내부 클래스/구조가 바뀌면 이 선택자가 무력화될 수 있음(`.gradio-container` 하위 내부 클래스는 버전 간 안정성이 보장되지 않는 비공개 구현 세부사항).
- **후속 작업**: 없음

### 배운 점
체크박스를 자유 배치(`position:absolute`)하는 순간, 그 체크박스들을 감싸는 프레임워크의 자동 wrapper div가 콘텐츠 높이를 정상적으로 계산하지 못하고 붕괴할 수 있다. 최종적으로 스타일링한 자식 요소 자체가 아니라 "내가 만들지 않은 중간 wrapper"를 의심하고 DOM 체인 전체를 훑는 것이 핵심이었다 — 눈에 보이는 증상(베이스가 잘림)과 실제 원인(안 보이는 중간 wrapper의 auto-height 붕괴)이 전혀 직관적으로 이어지지 않았다.

### 참고
- 없음 (Gradio 공식 문서에 `.form` wrapper 내부 구조 명세가 없어, 런타임 DOM 조사로 직접 확인)
