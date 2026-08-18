# 다음 세션 인계 (2026-08-18 종료 시점)

트랙 A(예측 정확도 고도화) 진행 중. 계획서: `docs/superpowers/plans/2026-08-16-prediction-accuracy.md`

## 지금 어디까지 왔나

| Task | 상태 | 커밋 |
|---|---|---|
| 1 선수 이름 룩업 | 완료 | `c200826` |
| 2 prior 빌더 | 완료 | `7f73a9b` |
| 3 시간·피로 피처 | 완료 | `6444218` |
| 4 파이프라인 + 누수 테스트 | 완료 | `0d17757` |
| 5 피처 기여분 측정 (게이트) | 완료 — 미달이나 사용자 판단으로 진행 | `74415ff` |
| 6 LightGBM 전환 | 완료 — 게이트 통과 | `cf304d0` |
| 10 서빙 통합 | 완료 (순서 앞당김) | `e3098d3` |
| — 재랭킹 기여도 측정 | 완료 — 조치 없음 | `d0a3b74` |
| 7 GRU | 완료 — TS-010 해결 후 학습 완주 | `c6b0c75` |
| 8 앙상블 (게이트) | 완료 — 게이트 통과 | `923cf47` |
| — 앙상블 서빙 반영 | 완료 — 서빙 top-1 43.26 → 43.84% | `1cc196b` |
| — 타자 피처 누수 수정 | 완료 — train 경기만 집계 | `020f203` |
| — 타자 x 구종 피처 측정 | 완료 — 이득 없어 미채택 | `969877f` |
| 9 확률 캘리브레이션 | 미착수 | |
| 11 배포 아티팩트 + Render 검증 | 코드·검증 완료 / 배포 확인은 PR #1 머지 후 | `bef4ddd` |
| 12 문서 + ADR-0003 | 미착수 | |

테스트 53 → 111건 (전체 스위트 2초 통과).

## 정확도 현황

| | 시작 | 현재 (서빙 실측) | 목표 |
|---|---|---|---|
| top-1 | 39.5% | 43.84% | 47% |
| top-3 | 78.7% | 86.38% | 85% (달성) |

- top-3는 목표 달성. top-1이 3.2%p 남았다.
- 모델 크기 188MB → 9.89MB(+ GRU 61KB), 추론 23.6ms → 1.73ms.
- 개선분 분해: 피처 보강 top-1 +2.6%p, 모델 교체 +1.6%p, 앙상블 +0.59%p.
- 상세는 `docs/PERFORMANCE.md`.

## 완료: TS-010 — GRU 학습 교착

해결됨. 원인은 스레드풀도 데이터 크기도 아니고 dylib 로드 순서였다.
pyarrow와 TensorFlow가 둘 다 absl 심볼을 weak definition으로 export 하는데, macOS dyld는
weak 정의를 이미지 간에 합치고 먼저 로드된 쪽이 이긴다. `import pandas`가 pyarrow를 먼저
끌고 들어오면 TF가 Arrow판 absl 뮤텍스를 쓰게 되고 첫 eager 연산에서 깨어나지 않는 락을
기다린다.

수정: `scripts/train_seq.py`에서 `import keras`를 pandas보다 먼저. 한 줄이다.

같은 원인이 pytest에도 잠복해 있었다(파일 개별로는 106건 전부 통과, 붙이면 교착).
`tests/conftest.py` 신설로 막았다. 상세는 `TROUBLESHOOTING.md` TS-010.

학습 결과 — 20에폭 323초:

| | val top-1 | val top-3 | test top-1 | test top-3 |
|---|---|---|---|---|
| GRU (numpy 서빙 경로) | 38.34% | 78.35% | 39.02% | 79.36% |

전날 예측대로 LightGBM(43.7%)보다 4.7%p 낮다.

## 완료: Task 8 앙상블 게이트

`p = (1-w)*LightGBM + w*GRU`, w는 val에서만 선택 → w=0.30.

| | 단독 | 앙상블 | 차이 | McNemar |
|---|---|---|---|---|
| val top-1 | 43.95% | 44.15% | +0.20%p | p=0.039 |
| test top-1 | 43.62% | 44.08% | +0.46%p | p=1.1e-06 |
| test top-3 | 85.74% | 86.55% | +0.81%p | |

게이트를 통과했다. 처음 쟀을 때는 val McNemar가 p=0.103이라 val에서 노이즈와 구분이
안 됐는데, 타자 피처 누수를 고치고 다시 재니 p=0.039로 내려갔다. 누수가 단독 쪽만
부풀리고 있었다.

재현: `./venv/bin/python scripts/eval_ensemble.py`

## 완료: 앙상블 서빙 반영

`services/prediction_service.py`가 LightGBM 확률에 GRU를 w=0.30으로 섞는다.
GRU는 numpy 추론기로 돌아서 TensorFlow 의존성이 늘지 않는다. 배포에 더 얹는 건
`models/seq_model_weights.npz` 61KB 하나뿐이다.

서빙 구성에서 다시 잰 값이다. 세 피처를 train 대표값으로 고정하고 pitch_of_atbat을
balls+strikes+1로 근사한, 앱이 실제로 만드는 입력이다.

| 구성 | top-1 | top-3 |
|---|---|---|
| 전 피처 실측 (단독) | 43.62% | 85.74% |
| 서빙 구성 (단독) | 43.26% | 85.56% |
| 서빙 구성 (앙상블) | 43.84% | 86.38% |

서빙에서 이득이 +0.59%p로 오프라인 +0.46%p보다 크다(McNemar p=5.5e-10). GRU가 보는
lag 피처는 서빙에서 전부 관측되니까, 고정한 세 피처 때문에 깎인 부분을 GRU가 일부
메운다. 그래서 앙상블 서빙이 전 피처 실측 단독보다도 높다.

npz가 없으면 LightGBM 단독으로 조용히 폴백한다. `PredictionService(ensemble=False)`로도
끌 수 있다.

재현: `./venv/bin/python scripts/eval_serving.py`

## 타자 x 구종 피처 — 재봤고, 안 된다

가장 기대했던 후보였는데 이득이 없었다. 측정 결과다.

| 구성 | 피처 수 | test top-1 | base 대비 | McNemar |
|---|---|---|---|---|
| base | 88 | 43.71% | — | — |
| whiff만 11열 | 99 | 43.60% | -0.11%p | p=0.21 |
| 전체 33열 | 121 | 43.50% | -0.21%p | p=0.023 |

- 열이 많아서 희석된 게 아니다. 제일 마른 형태(whiff 11열)도 이득 0이다.
- 모델이 무시한 것도 아니다. 33열이 gain의 5%를 가져가는데 정확도는 오히려 떨어진다.
- 이 지표는 "타자가 그 구종을 못 친다"를 말하고, 우리가 맞히려는 건 "투수가 다음에
  뭘 던지나"다. 둘이 생각만큼 안 이어진다.

이 측정은 누수를 고치기 전 데이터로 했다. 세 줄이 같은 데이터라 차이는 유효하고
기준선 절대값만 지금과 다르다(43.71% -> 43.62%).

파이프라인 기본값은 꺼 뒀다(`--with-batter-pitch`로 켬). 코드와 테스트는 남겼다.
상세는 `docs/PERFORMANCE.md`.

## 완료: 타자 피처 누수 수정

`batter_whiff_avg` 같은 4개는 연도 전체로 집계된 비율을 쓰고 있었다. 어느 타자를 쓸지만
train으로 걸렀지 비율 자체에 val/test 경기가 들어갔다. 오늘 만든 이벤트 표로 train
경기만 잘라 다시 집계했다.

| | 수정 전 | 수정 후 |
|---|---|---|
| test top-1 | 43.71% | 43.62% |
| test top-3 | 85.73% | 85.74% |

내려가는 게 정상이다. 누수는 오프라인 점수만 올린다. 폭이 작은 건 이 피처들의 gain
비중이 1.54%라서다. 곁다리로 앙상블 val McNemar가 p=0.103에서 p=0.039로 내려갔다.

`build_batter_matchup_features`가 이제 프로파일이 아니라 이벤트 표를 받는다.
`batter_matchup_profile`은 scouting_service의 화면 표시용으로만 남는다.

## 완료: Task 11 배포 아티팩트 정리

2티어 아티팩트를 없앴다. LightGBM이 9.89MB라 축소판을 따로 둘 이유가 없어졌다.

지운 것: `scripts/train_deploy_model.py`, `models/next_pitch_model_deploy.joblib`(38MB),
`render.yaml`의 `PITCH_MODEL_FILE`. 서빙이 이미 LightGBM이라 그 38MB는 클론만 되고
로드된 적이 없었다.

배포 의존성에서 `scikit-learn`과 `joblib`을 뺐다. RandomForest를 언피클할 때만
필요했는데 추론 경로에서 빠졌다. `backend="rf"`는 로컬 비교용으로 남기고 joblib을
그 분기 안에서 지연 import 한다. `scipy`는 lightgbm이 자기 의존성으로 끌고 온다.

배포 의존성만 남기고(sklearn·joblib·TF·torch·faiss 차단) 실측한 값이다.

| | 값 |
|---|---|
| PredictionService 로드 / 메모리 | 0.80초 / 155MB |
| app.py 전체 로드 / 메모리 | 3.26초 / 349MB |

512MB 티어에서 160MB 정도 여유가 남는다. RAG가 `rag_service=None`으로 degrade 하는
것까지 확인했다.

남은 것은 Step 5 하나다. 실제 Render에 올려서 OOM 없이 분석 1회가 되는지 봐야 한다.
Render는 main에서 배포하므로 PR #1을 머지해야 확인할 수 있다.

https://github.com/jjssspark/DiamondScout-AI/pull/1

머지하면 자동 빌드가 돌고 `keep-warm.yml`이 10분마다 200을 확인하므로 실패는 바로
드러난다. 머지 후 데모에서 분석 1회를 돌려 OOM이 없는지 보면 Task 11이 끝난다.

## 남은 후보 (목표 47%까지 3.2%p)

1. LightGBM 하이퍼파라미터 — `best_iteration=89`로 조기 수렴했다. 2000라운드를
   허용했는데 89에서 멈춘 건 이례적으로 이르다. `learning_rate`를 낮추고
   `num_leaves`·`min_data_in_leaf`를 조정할 여지가 있다. 지금 시점에서 남은 것 중
   제일 그럴듯하다.
2. Task 9 캘리브레이션 — top-1은 안 오르고 확률값 신뢰도만 오른다.

타자 x 구종이 죽었으니 1번이 자동으로 1순위가 된다. 다만 하이퍼파라미터로 3%p가
나오는 경우는 드물다. 목표 47%가 이 피처 세트로 가능한 수치인지부터 다시 볼 필요가
있다.

## 남은 정리 작업

- `requirements-deploy.txt` 상단 주석은 갱신했다(LightGBM + GRU 앙상블, TF 불필요). ADR-0003 자체는 Task 12에 남아 있다.
- `README.md`에는 정확도 수치가 없다(`docs/PERFORMANCE.md` 링크만 있다). 확인 완료, 조치 불필요.
- `models/next_pitch_model.joblib`(188MB)은 `backend="rf"` 폴백용으로 남아 있다. Task 11에서 배포 아티팩트를 결정할 때 유지 여부를 판단할 것.
- `services/scouting_service.py`의 투수 모드 재랭킹은 정답 라벨이 없어 오프라인 검증이 원리적으로 불가능하다. 타자 모드만 측정했다는 점을 ADR에 남길 것.

## 재현에 필요한 명령

```bash
# 전처리부터 다시 (raw 242MB -> processed)
./venv/bin/python data/preprocess_statcast.py --year 2025

# 보강 split + 서빙 prior 생성 (둘은 항상 같이 만들어진다)
./venv/bin/python data/build_enriched_dataset.py --year 2025

# LightGBM 학습
./venv/bin/python scripts/train_lgbm.py

# GRU 학습 (앙상블용, 선택)
./venv/bin/python scripts/train_seq.py

# 서빙 구성 정확도 확인
./venv/bin/python scripts/eval_serving.py

# 앱
./venv/bin/python app.py   # http://localhost:7862
```

`data/processed/enriched_*.parquet`와 `next_pitch_dataset_*.csv`는 gitignore 대상이다.
클론 직후에는 위 두 명령을 먼저 돌려야 한다.
