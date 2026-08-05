# ADR (Architecture Decision Record)

DiamondScout_AI의 주요 아키텍처 결정을 기록한다. 형식은 Michael Nygard 스타일(Context → Decision → Consequences)을 따른다.

관련 문서: 프레임워크 버그·환경 이슈는 [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)에 별도로 기록한다. ADR은 "왜 이 구조를 택했는가", TROUBLESHOOTING은 "무엇이 왜 깨졌고 어떻게 고쳤는가"를 다룬다.

| ID | 제목 | 상태 |
|---|---|---|
| [ADR-0001](#adr-0001--다음-구종-예측--randomforest를-프로덕션에-lstm은-평가용으로-유지) | 다음 구종 예측 — RandomForest를 프로덕션에, LSTM은 평가용으로 유지 | Accepted |
| [ADR-0002](#adr-0002--instant-scout-qa--faiss-rag--ollama-로컬-llm-채택) | Instant Scout Q&A — FAISS RAG + Ollama 로컬 LLM 채택 | Accepted |
| [ADR-0003](#adr-0003--ui-프레임워크로-gradio-채택) | UI 프레임워크로 Gradio 채택 | Accepted |

---

## ADR-0001 · 다음 구종 예측 — RandomForest를 프로덕션에, LSTM은 평가용으로 유지

**상태**: Accepted
**날짜**: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 2025시즌 Statcast 데이터로 다음 투구 구종(11개 클래스)을 예측하는 모델이 필요했다.
- 먼저 RandomForest baseline(`models/next_pitch_model.py`)을 학습해 `joblib`으로 직렬화하고, 서비스(`services/prediction_service.py`)에서 로드해 쓰도록 구현했다.
- 이후 정확도 개선을 위해 LSTM + Dense 딥러닝 모델(`models/deep_next_pitch_model.py`, TensorFlow/Keras)을 별도로 학습·평가했다.
- 오프라인 평가 결과(`data/processed/model_outputs/metrics_2025.json`, `deep_metrics_2025.json`):

  | 모델 | 테스트 셋 크기 | top-1 정확도 | top-3 정확도 |
  |---|---|---|---|
  | RandomForest | 88,983건 | 39.5% | 78.7% |
  | LSTM | 10,000건 | 40.7% | 81.6% |

  LSTM이 두 지표 모두 우위지만, **두 모델의 테스트 셋 크기가 다르다** — RF는 held-out 전체(88,983건), LSTM은 10,000건 서브셋으로 평가되어 엄밀한 동일 조건 비교는 아니다.

### Decision

프로덕션 추론 경로는 **RandomForest만 사용한다.**

`PredictionService.__init__`은 `load_deep_model: bool = False`가 기본값이고, 딥러닝 모델을 로드하는 코드(`_load_deep_model`)는 존재하지만 `load_deep_model=True`로 호출하는 곳이 서비스 전체에 없다. 즉 LSTM은 학습·평가까지 끝났지만 **실제 사용자 요청에는 연결돼 있지 않다.**

코드 주석에 남긴 근거를 그대로 인용한다:

> "딥러닝 모델(models/deep_next_pitch_model.keras)은 TensorFlow가 무거운 의존성이므로 기본적으로는 로드하지 않고, load_deep_model=True일 때만 선택적으로 로드하는 구조만 준비한다."

### Consequences

**장점**
- 서비스 시작 시간·메모리 사용량이 가볍다. scikit-learn만으로 배포 가능하고, TensorFlow(및 CUDA 등 부수 의존성)를 프로덕션 런타임에서 피할 수 있다.
- 1인 개발·개인 프로젝트 규모에서 배포 단순성의 이득이 정확도 1~3%p 개선보다 크다고 판단했다.

**단점**
- 오프라인 평가에서 더 정확한 모델(LSTM)이 실제 사용자에게는 적용되지 않는 상태로 남아 있다 — "정확도보다 배포 단순성"을 택한 트레이드오프이며, 포트폴리오에 성과 지표를 쓸 때 "어느 모델이 실제 서비스에 쓰이는지"를 명확히 구분해야 한다.
- RF·LSTM 비교가 서로 다른 크기의 테스트 셋 기준이라, 지금 수치로 "LSTM이 X%p 더 낫다"고 단정하는 건 방법론적으로 약하다.

### 후속 과제

- LSTM을 실제로 서비스에 연결하려면: (1) 두 모델을 **동일한 테스트 셋**으로 재평가해 공정하게 비교, (2) TensorFlow 의존성을 프로덕션에 들일지 여부(콜드 스타트 시간, 배포 크기)를 다시 결정.
- 그전까지는 "LSTM이 RF보다 낫다"는 표현은 "오프라인 평가 기준"이라는 단서를 항상 붙인다.

---

## ADR-0002 · Instant Scout Q&A — FAISS RAG + Ollama 로컬 LLM 채택

**상태**: Accepted
**날짜**: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 분석 결과(추천 구종, 위험도, 상대 약점 등)에 대해 사용자가 자연어로 후속 질문("왜 이 구종을 추천했어?", "이 공을 노려도 돼?")을 하면 답해주는 기능이 필요했다.
- `docs/PRD.md`에 명시된 프로젝트 목적 자체가 "수업에서 배운 Hugging Face 임베딩, FAISS 기반 RAG, Ollama 로컬 LLM, Gradio UI, Transformer 구조를 야구 전력분석 서비스에 적용"하는 것이었다 — 즉 이 스택 선택은 순수 엔지니어링 최적화가 아니라 **수업 커리큘럼 요구사항**이 우선 조건이었다.
- 상용 LLM API(OpenAI 등)는 과금·키 관리가 필요해 개인 프로젝트/수업 시연 목적과 맞지 않았다.

### Decision

- `services/rag_service.py`가 매 분석 직후 그 결과를 FAISS 인덱스에 넣고, 사용자 질문에 대해 관련 컨텍스트를 검색(RAG)한다.
- `services/coach_agent.py`(`CoachAgent`)가 검색된 컨텍스트 + 대화 history + 최신 분석 결과를 로컬 Ollama 서버(`http://localhost:11434`, 모델 `gemma2:latest`)에 넘겨 답변을 생성한다.
- 견고성을 위해 이중 방어 구조를 둔다:
  - Ollama 가용성을 먼저 짧은 타임아웃(1.5초)으로 확인
  - 답변 생성 자체는 25초 타임아웃
  - 위 두 경우 및 RAG 검색 실패까지, 어느 단계가 실패해도 예외를 흡수해 규칙 기반(rule-based) 안내 답변으로 폴백한다 — LLM/RAG 계층이 통째로 죽어도 채팅 기능 자체는 안내 메시지로 응답하며 앱이 죽지 않는다.

### Consequences

**장점**
- API 키·과금 없이 완전히 로컬에서 동작 — 개인 프로젝트/수업 시연에 적합.
- 커리큘럼 요구사항(Hugging Face·FAISS·Ollama·Gradio)을 그대로 충족.
- 실패 격리(fallback) 구조 덕분에 로컬에 Ollama가 없거나 꺼져 있어도 앱 자체는 정상 동작.

**단점**
- 사용자 로컬 환경에 Ollama가 설치·구동돼 있어야 실제 LLM 답변 품질을 볼 수 있다 — 데모 환경 의존성이 크다.
- `gemma2:latest`는 상용 대형 모델 대비 추론 품질·일관성이 낮을 수 있다(예: 서로 다른 질문에 유사한 답변이 나오는 경우 관찰됨).
- RAG 인덱스가 분석 1회당 매번 새로 빌드되는 구조라, 대화가 길어지거나 여러 번 재분석하면 컨텍스트 관리 비용이 늘어날 수 있다.

---

## ADR-0003 · UI 프레임워크로 Gradio 채택

**상태**: Accepted
**날짜**: 2026-08-05 (기록일. 실제 결정은 코드 기준 그 이전에 이루어짐)

### Context

- 1인 개발로 데이터 입력 폼(STEP1~4 마법사), 결과 시각화(스트라이크존 히트맵), PDF 리포트, 채팅 Q&A까지 하나의 앱으로 빠르게 만들어야 했다.
- `docs/PRD.md`에 "수업자료와 맞춰 Gradio 기반으로 시연한다"고 명시돼 있다 — React 등 별도 프론트엔드를 구축할지 말지를 자유롭게 고른 것이 아니라, **수업 커리큘럼이 Gradio 사용을 전제조건으로 요구**했다.

### Decision

투수/타자 모드, STEP1~4 마법사, 코칭 보드, PDF 다운로드, Instant Scout Q&A까지 전부 Gradio 6.x `Blocks` + `gr.Tabs`(단계 전환) + `gr.State`(단계·분석 결과 상태 관리)로 구현한다. 커스텀 프론트엔드(별도 React/Vue 앱 + API 서버)는 만들지 않는다.

### Consequences

**장점**
- Python만으로 백엔드(모델 추론·RAG·LLM)와 프론트엔드를 한 파일(`app.py`)에서 통합 개발 — 별도 API 계약이나 배포 파이프라인이 필요 없다.
- `share=True` 옵션으로 즉시 임시 공개 링크(`*.gradio.live`)를 생성할 수 있어 데모·시연이 빠르다.
- 수업 커리큘럼 요구사항을 그대로 충족.

**단점**
- Gradio의 컴포넌트 `visible=` 갱신에 프레임워크 버그성 동작이 있다 — 예: 컴포넌트가 Python 쪽 정적 초기값에서 벗어나는 **첫 번째** `visible=` 전환이 새로고침 직후 100% 렌더링 누락되는 문제를 겪었고, `demo.load()`로 그 첫 전환을 미리 소진시키는 우회 패턴을 도입해야 했다(`TROUBLESHOOTING.md` TS-003 참고).
- 세밀한 커스텀 인터랙션(실시간 채팅 애니메이션, 정교한 레이아웃 제어 등)은 Gradio 내부 DOM 클래스에 의존하는 CSS 오버라이드로 처리해야 해서, 커스텀 프론트엔드 대비 유지보수 리스크가 있다(Gradio 버전이 올라가면 내부 클래스명이 바뀌어 CSS가 깨질 수 있음).
- 단일 파일(`app.py`)에 UI·이벤트 배선이 모두 몰려 있어, 프로젝트가 더 커지면 분리가 필요해질 수 있다.
