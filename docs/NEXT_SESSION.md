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
| — 앙상블 서빙 반영 | 완료 — 서빙 top-1 43.25 → 43.80% | (미커밋) |
| — 타자 x 구종 피처 측정 | 완료 — 이득 없어 미채택 | (미커밋) |
| 9 확률 캘리브레이션 | 미착수 | |
| 11 배포 아티팩트 + Render 검증 | 미착수 | |
| 12 문서 + ADR-0003 | 미착수 | |

테스트 53 → 111건 (전체 스위트 2초 통과).

## 정확도 현황

| | 시작 | 현재 (서빙 실측) | 목표 |
|---|---|---|---|
| top-1 | 39.5% | **43.80%** | 47% |
| top-3 | 78.7% | **86.37%** | 85% (달성) |

- top-3는 목표 달성. top-1이 3.2%p 남았다.
- 모델 크기 188MB → 9.89MB(+ GRU 61KB), 추론 23.6ms → 1.73ms.
- 개선분 분해: 피처 보강 top-1 +2.6%p, 모델 교체 +1.6%p, 앙상블 +0.55%p.
- 상세는 `docs/PERFORMANCE.md`.

## 완료: TS-010 — GRU 학습 교착

**해결됨.** 원인은 스레드풀도 데이터 크기도 아니고 **dylib 로드 순서**였다.
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

`p = (1-w)*LightGBM + w*GRU`, w는 val에서만 선택 → **w=0.30**.

| | 단독 | 앙상블 | 차이 | McNemar |
|---|---|---|---|---|
| val top-1 | 44.02% | 44.18% | +0.16%p | p=0.103 (유의하지 않음) |
| test top-1 | 43.71% | **44.13%** | +0.42%p | p=1.6e-05 (유의) |
| test top-3 | 85.73% | **86.44%** | +0.71%p | |

게이트 문구는 통과했으나 val 이득은 노이즈와 구분되지 않는다. 채택 근거는 test와
가중치 곡선 모양이다(w=0.05~0.35 일곱 개가 전부 단독 초과, top-3도 동반 상승).

재현: `./venv/bin/python scripts/eval_ensemble.py`

## 완료: 앙상블 서빙 반영

`services/prediction_service.py`가 LightGBM 확률에 GRU를 w=0.30으로 섞는다.
GRU는 numpy 추론기로 돌아서 TensorFlow 의존성이 늘지 않는다. 배포에 더 얹는 건
`models/seq_model_weights.npz` 61KB 하나뿐이다.

서빙 구성에서 다시 잰 값이다. 세 피처를 train 대표값으로 고정하고 pitch_of_atbat을
balls+strikes+1로 근사한, 앱이 실제로 만드는 입력이다.

| 구성 | top-1 | top-3 |
|---|---|---|
| 전 피처 실측 (단독) | 43.71% | 85.73% |
| 서빙 구성 (단독) | 43.25% | 85.56% |
| 서빙 구성 (앙상블) | 43.80% | 86.37% |

서빙에서 이득이 +0.55%p로 오프라인 +0.42%p보다 크다(McNemar p=5.1e-09). GRU가 보는
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

파이프라인 기본값은 꺼 뒀다(`--with-batter-pitch`로 켬). 코드와 테스트는 남겼다.
상세는 `docs/PERFORMANCE.md`.

곁가지로 하나 알게 된 것: 기존 타자 피처 4개(`batter_whiff_avg` 등)의 비율은
연도 전체로 집계된 값이다. 어느 타자를 쓸지는 train으로 거르는데, 비율 자체는
val/test 경기까지 포함해서 계산된다. 이번에 만든 이벤트 표를 쓰면 train만으로
다시 만들 수 있다. 지금은 손대지 않았다.

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
