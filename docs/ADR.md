# ADR (Architecture Decision Record)

DiamondScout_AI의 주요 아키텍처 결정을 기록한다. 형식은 Michael Nygard 스타일(Context → Decision → Consequences)을 따른다.

관련 문서: 프레임워크 버그·환경 이슈는 [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)에 별도로 기록한다. ADR은 "왜 이 구조를 택했는가", TROUBLESHOOTING은 "무엇이 왜 깨졌고 어떻게 고쳤는가"를 다룬다.

| ID | 제목 | 상태 |
|---|---|---|
| [ADR-0001](#adr-0001--다음-구종-예측--randomforest를-프로덕션에-lstm은-평가용으로-유지) | 다음 구종 예측 — RandomForest를 프로덕션에, LSTM은 평가용으로 유지 | Superseded by ADR-0006 |
| [ADR-0002](#adr-0002--instant-scout-qa--faiss-rag--ollama-로컬-llm-채택) | Instant Scout Q&A — FAISS RAG + Ollama 로컬 LLM 채택 | Accepted |
| [ADR-0003](#adr-0003--ui-프레임워크로-gradio-채택) | UI 프레임워크로 Gradio 채택 | Accepted |
| [ADR-0004](#adr-0004--db-로깅-실패-시-핵심-기능-무중단-설계) | DB 로깅 실패 시 핵심 기능 무중단 설계 | Accepted |
| [ADR-0005](#adr-0005--gradio-sharetrue-임시-터널로-배포) | Gradio `share=True` 임시 터널로 배포 | Superseded (Render 전환) |
| [ADR-0006](#adr-0006--다음-구종-예측--피처-보강--lightgbm--gru-앙상블로-전환) | 다음 구종 예측 — 피처 보강 + LightGBM + GRU 앙상블로 전환 | Accepted |

---

## ADR-0001 · 다음 구종 예측 — RandomForest를 프로덕션에, LSTM은 평가용으로 유지

> 상태: Superseded by [ADR-0006](#adr-0006--다음-구종-예측--피처-보강--lightgbm--gru-앙상블로-전환) (2026-08-18)
> 여기 적힌 "후속 과제" 두 개가 ADR-0006에서 실제로 처리됐다. 모델을 같은 테스트 셋으로 다시 비교했고, TensorFlow를 프로덕션에 들일지도 결론이 났다.

상태: Superseded
날짜: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 2025시즌 Statcast 데이터로 다음 투구 구종(11개 클래스)을 예측하는 모델이 필요했다.
- 먼저 RandomForest baseline(`models/next_pitch_model.py`)을 학습해 `joblib`으로 직렬화하고, 서비스(`services/prediction_service.py`)에서 로드해 쓰도록 구현했다.
- 이후 정확도 개선을 위해 LSTM + Dense 딥러닝 모델(`models/deep_next_pitch_model.py`, TensorFlow/Keras)을 별도로 학습·평가했다.
- 오프라인 평가 결과(`data/processed/model_outputs/metrics_2025.json`, `deep_metrics_2025.json`):

  | 모델 | 테스트 셋 크기 | top-1 정확도 | top-3 정확도 |
  |---|---|---|---|
  | RandomForest | 88,983건 | 39.5% | 78.7% |
  | LSTM | 10,000건 | 40.7% | 81.6% |

  LSTM이 두 지표 모두 우위지만, 두 모델의 테스트 셋 크기가 다르다 — RF는 held-out 전체(88,983건), LSTM은 10,000건 서브셋으로 평가되어 엄밀한 동일 조건 비교는 아니다.

### 선택지

1. RandomForest만 유지 — 가볍고 배포 단순, 정확도는 상대적으로 낮음
2. LSTM으로 전환 — 오프라인 지표는 더 좋지만 TensorFlow 의존성을 프로덕션에 들여야 함
3. 둘 다 준비해두고 기본은 RF, 옵션으로 LSTM — 현재 코드가 실제로 이 형태(`load_deep_model` 플래그)로 준비돼 있으나 호출부에서 켜는 곳이 없어 사실상 1번과 동일하게 동작

### Decision

프로덕션 추론 경로는 RandomForest만 사용한다.

`PredictionService.__init__`은 `load_deep_model: bool = False`가 기본값이고, 딥러닝 모델을 로드하는 코드(`_load_deep_model`)는 존재하지만 `load_deep_model=True`로 호출하는 곳이 서비스 전체에 없다. 즉 LSTM은 학습·평가까지 끝났지만 실제 사용자 요청에는 연결돼 있지 않다.

코드 주석에 남긴 근거를 그대로 인용한다:

> "딥러닝 모델(models/deep_next_pitch_model.keras)은 TensorFlow가 무거운 의존성이므로 기본적으로는 로드하지 않고, load_deep_model=True일 때만 선택적으로 로드하는 구조만 준비한다."

### Consequences

장점
- 서비스 시작 시간·메모리 사용량이 가볍다. scikit-learn만으로 배포 가능하고, TensorFlow(및 CUDA 등 부수 의존성)를 프로덕션 런타임에서 피할 수 있다.
- 1인 개발·개인 프로젝트 규모에서 배포 단순성의 이득이 정확도 1~3%p 개선보다 크다고 판단했다.

단점
- 오프라인 평가에서 더 정확한 모델(LSTM)이 실제 사용자에게는 적용되지 않는 상태로 남아 있다 — "정확도보다 배포 단순성"을 택한 트레이드오프이며, 포트폴리오에 성과 지표를 쓸 때 "어느 모델이 실제 서비스에 쓰이는지"를 명확히 구분해야 한다.
- RF·LSTM 비교가 서로 다른 크기의 테스트 셋 기준이라, 지금 수치로 "LSTM이 X%p 더 낫다"고 단정하는 건 방법론적으로 약하다.

### 후속 과제

- LSTM을 실제로 서비스에 연결하려면: (1) 두 모델을 동일한 테스트 셋으로 재평가해 공정하게 비교, (2) TensorFlow 의존성을 프로덕션에 들일지 여부(콜드 스타트 시간, 배포 크기)를 다시 결정.
- 그전까지는 "LSTM이 RF보다 낫다"는 표현은 "오프라인 평가 기준"이라는 단서를 항상 붙인다.

---

## ADR-0002 · Instant Scout Q&A — FAISS RAG + Ollama 로컬 LLM 채택

상태: Accepted
날짜: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 분석 결과(추천 구종, 위험도, 상대 약점 등)에 대해 사용자가 자연어로 후속 질문("왜 이 구종을 추천했어?", "이 공을 노려도 돼?")을 하면 답해주는 기능이 필요했다.
- `docs/PRD.md`에 명시된 프로젝트 목적 자체가 "수업에서 배운 Hugging Face 임베딩, FAISS 기반 RAG, Ollama 로컬 LLM, Gradio UI, Transformer 구조를 야구 전력분석 서비스에 적용"하는 것이었다 — 즉 이 스택 선택은 순수 엔지니어링 최적화가 아니라 수업 커리큘럼 요구사항이 우선 조건이었다.
- 상용 LLM API(OpenAI 등)는 과금·키 관리가 필요해 개인 프로젝트/수업 시연 목적과 맞지 않았다.

### 선택지

1. 상용 LLM API (OpenAI 등) — 답변 품질은 높지만 매치업 데이터를 외부로 보내야 하고 과금·키 관리 부담
2. 로컬 LLM (Ollama) + RAG — 데이터가 로컬을 벗어나지 않고 과금 없음, 다만 모델 품질이 상용 대비 낮음
3. 규칙 기반 응답만 사용 (LLM 없음) — 가장 단순하고 안정적이지만 자연어 후속 질문에 대응 불가

### Decision

- `services/rag_service.py`가 매 분석 직후 그 결과를 FAISS 인덱스에 넣고, 사용자 질문에 대해 관련 컨텍스트를 검색(RAG)한다.
- `services/coach_agent.py`(`CoachAgent`)가 검색된 컨텍스트 + 대화 history + 최신 분석 결과를 로컬 Ollama 서버(`http://localhost:11434`, 모델 `gemma2:latest`)에 넘겨 답변을 생성한다.
- 견고성을 위해 이중 방어 구조를 둔다:
  - Ollama 가용성을 먼저 짧은 타임아웃(1.5초)으로 확인
  - 답변 생성 자체는 25초 타임아웃
  - 위 두 경우 및 RAG 검색 실패까지, 어느 단계가 실패해도 예외를 흡수해 규칙 기반(rule-based) 안내 답변으로 폴백한다 — LLM/RAG 계층이 통째로 죽어도 채팅 기능 자체는 안내 메시지로 응답하며 앱이 죽지 않는다.

### Consequences

장점
- API 키·과금 없이 완전히 로컬에서 동작 — 개인 프로젝트/수업 시연에 적합.
- 커리큘럼 요구사항(Hugging Face·FAISS·Ollama·Gradio)을 그대로 충족.
- 실패 격리(fallback) 구조 덕분에 로컬에 Ollama가 없거나 꺼져 있어도 앱 자체는 정상 동작.

단점
- 사용자 로컬 환경에 Ollama가 설치·구동돼 있어야 실제 LLM 답변 품질을 볼 수 있다 — 데모 환경 의존성이 크다.
- `gemma2:latest`는 상용 대형 모델 대비 추론 품질·일관성이 낮을 수 있다(예: 서로 다른 질문에 유사한 답변이 나오는 경우 관찰됨).
- RAG 인덱스가 분석 1회당 매번 새로 빌드되는 구조라, 대화가 길어지거나 여러 번 재분석하면 컨텍스트 관리 비용이 늘어날 수 있다.

### 후속 결정 — 공개 데모 배포용 LLM 백엔드 스왑 (2026-08-05)

맥락: 포트폴리오용 공개 데모를 HF Spaces에 올리려 했으나, Spaces에는 Ollama를 상시 구동할 수 없다(컨테이너에 직접 설치하려면 `gemma2` 모델(~5GB) 풀링 때문에 무료 CPU 티어에서 콜드스타트가 느리거나 실패할 위험이 크다).

결정: "로컬 우선" 원칙 자체는 유지하되, `services/coach_agent.py`의 `CoachAgent`에 `LLM_BACKEND` 환경변수로 전환 가능한 백엔드를 추가했다.
- `LLM_BACKEND=ollama`(기본값, 로컬 개발) — 기존 동작 그대로.
- `LLM_BACKEND=groq` + `GROQ_API_KEY` — Groq의 무료 티어 hosted LLM(`llama-3.1-8b-instant`)을 대신 호출. `GROQ_API_KEY`가 비어 있으면 자동으로 규칙 기반 폴백으로 떨어져, 배포 환경에 키를 깜빡 안 넣어도 앱이 죽지 않는다.
- Ollama와 완전히 동일한 이중 방어 구조(가용성 확인 → 실패 시 규칙 기반 폴백, 반복 답변 감지 시 재시도)를 백엔드에 상관없이 그대로 재사용한다(`_is_llm_available`/`_call_llm`로 일반화).

결과: 로컬 개발자 경험은 전혀 바뀌지 않고(환경변수 미설정 시 기존 Ollama 그대로), 공개 데모만 Groq로 Q&A가 실제로 동작하게 된다. "로컬 LLM만 사용"이라는 원래 결정을 어기는 게 아니라, 그 원칙이 성립하지 않는 배포 환경 하나에만 예외를 뒀다.

---

## ADR-0003 · UI 프레임워크로 Gradio 채택

상태: Accepted
날짜: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 1인 개발로 데이터 입력 폼(STEP1~4 마법사), 결과 시각화(스트라이크존 히트맵), PDF 리포트, 채팅 Q&A까지 하나의 앱으로 빠르게 만들어야 했다.
- `docs/PRD.md`에 "수업자료와 맞춰 Gradio 기반으로 시연한다"고 명시돼 있다 — React 등 별도 프론트엔드를 구축할지 말지를 자유롭게 고른 것이 아니라, 수업 커리큘럼이 Gradio 사용을 전제조건으로 요구했다.

### 선택지

1. React/Vue + 별도 API 서버 — 커스텀 인터랙션·유지보수성은 좋지만 API 계약·배포 파이프라인이 추가로 필요, 커리큘럼 요구사항 밖
2. Streamlit — Gradio와 유사한 단일 파일 구조지만 커리큘럼이 명시적으로 Gradio를 지정
3. Gradio — 커리큘럼 요구사항을 그대로 충족, 챗봇·파일 업로드 등 필요한 컴포넌트가 내장돼 있음

### Decision

투수/타자 모드, STEP1~4 마법사, 코칭 보드, PDF 다운로드, Instant Scout Q&A까지 전부 Gradio 6.x `Blocks` + `gr.Tabs`(단계 전환) + `gr.State`(단계·분석 결과 상태 관리)로 구현한다. 커스텀 프론트엔드(별도 React/Vue 앱 + API 서버)는 만들지 않는다.

### Consequences

장점
- Python만으로 백엔드(모델 추론·RAG·LLM)와 프론트엔드를 한 파일(`app.py`)에서 통합 개발 — 별도 API 계약이나 배포 파이프라인이 필요 없다.
- `share=True` 옵션으로 즉시 임시 공개 링크(`*.gradio.live`)를 생성할 수 있어 데모·시연이 빠르다.
- 수업 커리큘럼 요구사항을 그대로 충족.

단점
- Gradio의 컴포넌트 `visible=` 갱신에 프레임워크 버그성 동작이 있다 — 예: 컴포넌트가 Python 쪽 정적 초기값에서 벗어나는 첫 번째 `visible=` 전환이 새로고침 직후 100% 렌더링 누락되는 문제를 겪었고, `demo.load()`로 그 첫 전환을 미리 소진시키는 우회 패턴을 도입해야 했다(`TROUBLESHOOTING.md` TS-003 참고).
- 세밀한 커스텀 인터랙션(실시간 채팅 애니메이션, 정교한 레이아웃 제어 등)은 Gradio 내부 DOM 클래스에 의존하는 CSS 오버라이드로 처리해야 해서, 커스텀 프론트엔드 대비 유지보수 리스크가 있다(Gradio 버전이 올라가면 내부 클래스명이 바뀌어 CSS가 깨질 수 있음).
- 단일 파일(`app.py`)에 UI·이벤트 배선이 모두 몰려 있어, 프로젝트가 더 커지면 분리가 필요해질 수 있다.

---

## ADR-0004 · DB 로깅 실패 시 핵심 기능 무중단 설계

상태: Accepted
날짜: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 분석 실행/Q&A/시뮬레이션 투구 기록을 MariaDB에 남기는 `DBService`(`services/db_service.py`)가 있다.
- 개인 프로젝트 특성상 `.env`에 DB 접속 정보가 없거나, 로컬 MariaDB가 꺼져 있는 상태로 앱을 실행하는 경우가 흔하다(예: 데모 시연, 다른 컴퓨터에서 클론 직후).
- DB 로깅은 "기록"이 목적이지 서비스의 핵심 가치(구종 예측·코칭 리포트·Q&A)가 아니다.

### 선택지

1. DB 연결 실패 시 앱 기동 중단 — 로깅 누락을 절대 허용하지 않지만, DB 없이는 데모조차 못 켜는 구조가 됨
2. DB 연결 실패해도 핵심 기능은 그대로 동작, 로깅만 조용히 비활성화 — 로그가 비더라도 서비스는 항상 뜬다

### Decision

`DBService.__init__`에서 `.env`에 DB 설정이 없거나 초기 연결 확인(`_connect().close()`)이 실패하면 `self.enabled = False`로 두고 경고만 출력한 뒤 정상적으로 계속 진행한다. 이후 모든 `save_*` 메서드는 `_execute`를 거치는데, `enabled`가 `False`면 즉시 `None`을 반환하고, 연결 자체는 됐지만 저장 도중 예외가 나도 그 예외를 흡수해 `None`을 반환한다 — DB 문제로 예외가 호출부까지 전파되는 경로가 없다.

`DBService` docstring에 남긴 계약을 그대로 인용한다:

> "save_* 메서드는 성공 시 insert된 행의 id(int)를, DB 미설정/연결 실패/저장 실패 시 None을 반환하며 절대 예외를 던지지 않는다."

### Consequences

장점
- `.env`에 DB 정보를 안 채워도, MariaDB가 안 떠 있어도 앱의 핵심 기능(예측·리포트·Q&A)은 100% 동작 — 데모/시연/신규 클론 환경에서 마찰이 없다.
- 호출부(`app.py`, `services/scouting_service.py` 등)가 DB 성공/실패를 신경 쓰지 않고 반환값 `None` 여부만 보면 된다.

단점
- DB 저장 실패가 콘솔 경고로만 남고 사용자에게는 전혀 드러나지 않는다 — 운영 환경이라면 실패율 모니터링이 따로 필요하지만, 현재는 그런 계측이 없다.
- 연결 확인은 시작 시 1회뿐이라, 기동 후 DB가 살아나도 재확인 로직 없이 그 세션 동안은 계속 비활성 상태로 남는다(재시작해야 복구).

---

## ADR-0005 · Gradio `share=True` 임시 터널로 배포

> 상태: Superseded (2026-08-05, Render 무료 티어 배포로 전환)
> 여기 적힌 "단점"이 실제로 문제가 돼서 클라우드 배포로 옮겼다. 처음 고른 곳은
> Hugging Face Spaces였는데 생성 시점에 402가 떠서 Render로 갔다. 그 과정은
> TROUBLESHOOTING.md TS-006에 있고, 지금 배포 설정은 `render.yaml`이다.
> Render 전환 자체를 다루는 ADR은 아직 쓰지 않았다.

상태: Superseded
날짜: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 개인 프로젝트/수업 시연 목적으로, 별도 서버·도메인·SSL 설정 없이 외부에서 접속 가능한 링크가 필요했다.
- Gradio는 `launch(share=True)`만 주면 자체 터널링으로 `*.gradio.live` 공개 URL을 즉시 발급해준다(`app.py` 마지막 `demo.launch(server_name="0.0.0.0", server_port=7862, share=True)`).

### 선택지

1. 클라우드 배포 (Hugging Face Spaces, Railway, 자체 서버 등) — 링크가 영구적이지만 배포 파이프라인 구축·유지비용 발생, Ollama 로컬 LLM 의존성 때문에 그대로 옮기기도 어려움
2. Gradio `share=True` 임시 터널 — 설정 없이 즉시 공개 링크 발급, 대신 로컬 프로세스가 켜져 있어야 하고 최대 1주일 후 만료

### Decision

정식 배포 없이 `share=True` 임시 터널만 사용한다. 로컬에서 `python app.py`를 실행하는 동안에만 공개 링크가 유효하다.

### Consequences

장점
- 배포 인프라를 전혀 구축하지 않고 몇 초 만에 외부 공유 가능한 링크를 얻는다.
- Ollama(로컬 LLM)·MariaDB(로컬 DB) 등 로컬 의존성을 그대로 둔 채 시연할 수 있다 — 클라우드로 옮겼다면 이 의존성들을 별도로 해결해야 했다.

단점
- 링크가 최대 1주일만 유효하고, 로컬 프로세스가 꺼지면 즉시 죽는다 — 포트폴리오에 링크를 올려도 시간이 지나면 깨진 링크가 된다(README에 이 제약을 명시해둠).
- 진짜 프로덕션 배포 경험(도커라이징, 클라우드 배포, 도메인·SSL)은 이 프로젝트로 증명되지 않는다.


## ADR-0006 · 다음 구종 예측 — 피처 보강 + LightGBM + GRU 앙상블로 전환

상태: Accepted
날짜: 2026-08-18
대체 대상: ADR-0001

### Context

ADR-0001 시점의 프로덕션 모델은 RandomForest 56피처, test top-1 39.5%였다. 세 가지가 문제였다.

첫째, 모델이 투수가 누군지 몰랐다. 피처에 선수 ID가 없고 구속·궤적·카운트만 있었다.
같은 0-2 카운트라도 커브를 즐겨 던지는 투수와 슬라이더만 던지는 투수를 구분할 방법이
없었다. 실제로 학습 없이 카운트별 구종 비율을 룩업만 해도 top-1 40.5%가 나왔다.
학습한 모델이 룩업보다 겨우 나은 수준이었다는 뜻이다.

둘째, 모델이 188MB였다. Render 무료 티어가 512MB라 38MB로 줄인 배포 전용 아티팩트를
따로 만들어야 했고(top-1 -0.55%p), 티어가 둘로 갈렸다.

셋째, RF와 LSTM을 서로 다른 크기의 테스트 셋으로 비교하고 있었다(88,983건 vs 10,000건).
ADR-0001이 스스로 이 점을 한계로 적어뒀다.

### 선택지

1. RF에 피처만 보강한다 — 배포 구조를 안 건드림. 크기 문제는 남음
2. LightGBM으로 바꾼다 — 표 형태 다중분류에서 GBDT가 보통 우세하고 크기도 작음
3. 시퀀스 모델(LSTM/GRU)로 간다 — TensorFlow를 프로덕션에 들여야 함
4. 위를 섞는다

### Decision

피처를 보강하고 모델을 LightGBM으로 바꾼 뒤, GRU를 섞는다. 각 단계를 게이트로 나눠
따로 측정하고 통과한 것만 채택했다.

기여분을 분리해서 쟀다. 섞어서 재면 뭐가 효과를 냈는지 알 수 없다.

| 단계 | top-1 | top-3 |
|---|---|---|
| 피처 보강 (같은 RF, 56 -> 88피처) | +2.6%p | +4.8%p |
| 모델 교체 (같은 피처, RF -> LightGBM) | +1.6%p | +2.2%p |
| GRU 앙상블 | +0.46%p | +0.81%p |

피처 쪽 기여가 모델 교체보다 컸다. 진단이 맞았다는 뜻이다. 보강한 88피처 중 prior
22개가 gain의 81%를 진다. 투수 정체성 신호가 없던 게 실제 병목이었다.

LightGBM을 고른 이유는 두 가지다. 정확도가 RF보다 1.6%p 높고, 크기가 188MB에서
9.89MB로 19배 작다. 두 번째가 컸다. Render 512MB 제약이 풀리면서 배포 전용 축소
아티팩트를 만들 이유 자체가 사라졌다.

앙상블은 게이트를 세워두고 넘은 경우다. 기준은 "val에서 단일 모델을 못 이기면 안
쓴다"였다. w=0.30에서 val top-1 43.95% -> 44.15%, test 43.62% -> 44.08%였고, 짝지은
비교(McNemar)로도 val p=0.039 / test p=1.1e-06이었다.

GRU 단독은 39.0%로 LightGBM보다 4.6%p 낮다. 그런데 섞으면 오른다. 틀리는 지점이
달라서다. LightGBM은 gain의 81%를 prior에 쓰고 GRU는 prior를 아예 안 본다. 직전
5구의 궤적만 본다.

TensorFlow는 프로덕션에 들이지 않는다. ADR-0001이 남긴 후속 과제 중 하나였는데,
결론은 "안 들인다"다. 대신 GRU를 Keras로 학습하고 가중치만 npz로 내보내, 서빙에서는
numpy 순전파로 추론한다(`models/seq_infer.py`, 60줄). 배포에 늘어나는 건 61KB 파일
하나뿐이고 추론 비용은 1.67ms에서 1.77ms로 0.10ms 늘었다.

이 선택의 대가는 학습과 서빙이 갈린다는 점이다. 둘이 어긋나면 조용히 틀린 확률이
나온다. 그래서 `tests/test_seq_infer.py`가 같은 가중치로 Keras 출력과 numpy 출력이
일치하는지 확인하고, 학습 스크립트도 평가를 Keras가 아니라 numpy 추론기로 한다.

### 채택하지 않은 것

타자 x 구종 피처 (33열). 남은 후보 중 가장 기대했던 것이다. 지금 타자 피처는
whiff_rate 같은 값을 전 구종 평균 4개로 눌러서 "이 타자가 슬라이더에 약하다"가
사라진다. 구종 축을 살려서 다시 만들고 쟀는데 test top-1이 -0.21%p였다(McNemar
p=0.023, 열화 쪽이 유의). 열이 많아 희석된 것도 아니다. whiff만 11열로 줄여도 이득이
0이었다. 모델이 무시한 것도 아니다. 33열이 gain의 5%를 가져가면서 정확도는 떨어뜨렸다.

해석은 이렇다. 이 지표들은 "타자가 그 구종을 얼마나 못 치나"를 말하는데, 우리가
맞히려는 건 "투수가 다음에 뭘 던지나"다. 두 개가 생각만큼 이어지지 않는다.
코드는 `--with-batter-pitch` 플래그 뒤에 남겨 뒀다.

서비스 재랭킹 제거. 화면의 최종 추천은 모델 출력 그대로가 아니라 `ScoutingService`가
재랭킹한 결과다. 도입 근거였던 "모델에 선수 ID가 없다"는 전제가 prior 도입으로
사라져서 같은 정보를 두 번 반영하는지 측정했는데, 조치가 필요할 만큼의 차이가 없었다.

RandomForest 백엔드 삭제. `backend="rf"`는 로컬 비교용으로 남겼다. 아티팩트가
188MB라 저장소에 없어서 배포에서는 어차피 안 돈다. 지워도 되지만 비교 근거를 다시
만들 수 있게 두는 편이 낫다고 봤다.

### Consequences

좋아진 것

- 서빙 top-1 39.5% -> 43.84%, top-3 78.7% -> 86.38%. top-3 목표(85%)는 넘었다.
- 모델 188MB -> 9.95MB. 배포 티어를 하나로 합쳤다. `scripts/train_deploy_model.py`와
  38MB 축소 아티팩트, `PITCH_MODEL_FILE` 환경변수를 전부 없앴다.
- 추론 23.6ms -> 1.77ms.
- 배포 의존성에서 scikit-learn과 joblib이 빠졌다. TensorFlow는 들어온 적이 없다.
- 모든 모델을 같은 test split, 같은 표본(88,983건)으로 다시 비교했다. ADR-0001의
  후속 과제였다.

나빠지거나 남은 것

- 모델이 둘이 됐다. 학습 경로도 둘(`train_lgbm.py`, `train_seq.py`)이고 아티팩트도
  둘이다. 앙상블 가중치 0.30은 val에서 고른 값이라 데이터가 바뀌면 다시 골라야 한다.
- GRU는 학습만 Keras다. 학습 환경에는 TensorFlow가 필요하고, 그 과정에서 pyarrow와
  충돌하는 문제를 겪었다(TROUBLESHOOTING.md TS-010).
- prior가 gain의 81%를 진다. 서빙 prior 테이블이 학습에 쓴 것과 어긋나면 에러 없이
  정확도만 무너진다. 그래서 `data/build_enriched_dataset.py`가 학습 데이터와
  `models/serving_priors/`를 항상 같이 만든다.
- top-1 목표 47%에는 못 닿았다. 43.84%로 3.2%p 남았다. 남은 후보가 하이퍼파라미터
  정도인데 그것으로 3%p가 나오는 경우는 드물다. 47%가 이 피처 세트로 닿을 수 있는
  수치인지부터 다시 볼 필요가 있다.

### 후속 과제

- 확률 캘리브레이션은 마쳤다. 온도 스케일링으로 test ECE 0.0126 -> 0.0081. 순위를
  안 바꾸는 방식이라 top-k는 그대로다. 계수는 `models/calibration.json`에 있다.
- 실제 Render 배포에서 메모리 확인. 로컬(macOS) 실측은 app.py 전체 349MB다.
- 투수 모드 재랭킹은 정답 라벨이 없어 오프라인 검증이 원리적으로 불가능하다. 타자
  모드만 측정했다.

### 근거 자료

- `docs/PERFORMANCE.md` — 모든 수치의 출처와 재현 명령
- `output/metrics/` — `lgbm_metrics_2025.json`, `ensemble_gate_2025.json`,
  `serving_accuracy_2025.json`, `batter_pitch_gain_2025.json`, `feature_gain_2025.json`,
  `reliability_2025.png`
- 재현: `scripts/train_lgbm.py`, `scripts/train_seq.py`, `scripts/eval_ensemble.py`,
  `scripts/eval_serving.py`, `scripts/eval_batter_pitch_gain.py`, `scripts/calibrate_model.py`

---
