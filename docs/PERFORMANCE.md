# 성능·품질 지표

## 모델 정확도 (2025시즌 Statcast, held-out 평가)

| 모델 | 프로덕션 사용 여부 | 테스트 셋 | top-1 정확도 | top-3 정확도 |
|---|---|---|---|---|
| RandomForest | **사용 중** | 88,983건 | 39.5% | 78.7% |
| LSTM (Keras) | 미사용 (오프라인 평가만) | 10,000건 | 40.7% | 81.6% |

- 출처: `data/processed/model_outputs/metrics_2025.json`, `deep_metrics_2025.json`
- 두 모델이 서로 다른 크기의 테스트 셋으로 평가되어 있어 엄밀한 동일 조건 비교는 아니다. 근거와 트레이드오프는 [ADR-0001](ADR.md#adr-0001--다음-구종-예측--randomforest를-프로덕션에-lstm은-평가용으로-유지) 참고.

## 다음 구종 예측 응답 시간 (RandomForest, 로컬 측정)

측정 방법: `PredictionService`를 직접 호출해 동일 입력으로 20회 반복 추론(`predict_top_k`, k=3), `time.perf_counter()`로 측정. 환경: 로컬 macOS, 2026-08-05.

| 항목 | 값 |
|---|---|
| 모델 로드 (앱 기동 시 1회) | 1.873s |
| 추론 1회 평균 (20회) | 23.6ms |
| 추론 1회 최소/최대 | 14.4ms / 83.4ms |

모델 로드는 앱 기동 시 한 번만 발생하고, 이후 요청마다는 추론(수십 ms) 비용만 든다 — 사용자 체감 지연의 대부분은 예측이 아니라 아래 Q&A의 LLM 생성 구간에서 발생한다.

## Instant Scout Q&A 응답 시간 예산 (Ollama 로컬 LLM)

`services/coach_agent.py`가 실제 생성 소요 시간을 로깅하지 않아 성공 케이스의 정확한 분포는 아직 계측하지 못했다. 대신 코드에 설계된 타임아웃 예산과, 실제 로컬 실행 로그에서 관찰된 타임아웃 발생 사례를 근거로 남긴다.

| 단계 | 타임아웃 | 실패 시 동작 |
|---|---|---|
| Ollama 가용성 확인 | 1.5초 | 규칙 기반 폴백으로 즉시 전환 |
| 답변 생성 | 25초 | 규칙 기반 폴백으로 전환 |

로컬 실행 로그(`/private/tmp/diamondscout.log`, 2026-08-05)에서 실제로 이 타임아웃이 발동한 사례:
```
[경고] Ollama 답변 생성 실패, evidence 기반 fallback으로 대체: HTTPConnectionPool(host='localhost', port=11434): Read timed out. (read timeout=25)
```
`gemma2:latest` 같은 로컬 LLM은 하드웨어에 따라 생성 시간 편차가 커서, 25초 예산을 넘기는 경우가 실제로 발생한다 — 그래서 규칙 기반 폴백이 장식이 아니라 실제로 발동하는 경로임을 이 로그가 보여준다. 설계 근거는 [ADR-0002](ADR.md#adr-0002--instant-scout-qa--faiss-rag--ollama-로컬-llm-채택) 참고.

## 후속 계측 과제

- `CoachAgent`에 생성 소요 시간 로깅을 추가해 성공 케이스의 p50/p95 분포를 확보
- PDF 리포트 생성(`build_pdf_report`) 소요 시간 측정 — 현재 미계측
