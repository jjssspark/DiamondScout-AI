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
| **7 GRU** | **완료 — TS-010 해결 후 학습 완주** | (미커밋) |
| **8 앙상블 (게이트)** | **완료 — 게이트 통과, 서빙 미반영** | (미커밋) |
| 9 확률 캘리브레이션 | 미착수 | |
| 11 배포 아티팩트 + Render 검증 | 미착수 | |
| 12 문서 + ADR-0003 | 미착수 | |

테스트 53 → **106건** (전체 스위트 3.55초 통과).

## 정확도 현황

| | 시작 | 현재 (서빙 실측) | 목표 |
|---|---|---|---|
| top-1 | 39.5% | **43.25%** | 47% |
| top-3 | 78.7% | **85.56%** | 85% (달성) |

- **top-3는 목표 달성.** top-1이 3.75%p 남았다.
- 모델 크기 188MB → 9.89MB, 추론 23.6ms → 1.73ms.
- 개선분 분해: 피처 보강 top-1 +2.6%p, 모델 교체 +1.6%p.
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

게이트 문구는 통과했으나 **val 이득은 노이즈와 구분되지 않는다.** 채택 근거는 test와
가중치 곡선 모양(w=0.05~0.35 일곱 개가 전부 단독 초과, top-3도 동반 상승)이다.

**판단 필요 — 서빙에 반영할지 아직 결정하지 않았다.** 반영하면:
- 얻는 것: test 기준 top-1 +0.42%p, top-3 +0.71%p (목표까지는 여전히 2.87%p 부족)
- 드는 것: `models/seq_model_weights.npz`(0.06MB) 배포 추가, 서빙에서 시퀀스 조립 경로 필요

재현: `./venv/bin/python scripts/eval_ensemble.py`

## 다음 1순위: top-1을 메울 후보 (목표까지 2.87%p)

재랭킹 쪽은 이미 측정했고 여지가 없다(`docs/PERFORMANCE.md`의 "서비스 재랭킹의 기여도" 절). 남은 후보:

1. **LightGBM 하이퍼파라미터** — `best_iteration=89`로 조기 수렴했다. 2000라운드를 허용했는데 89에서 멈춘 건 이례적으로 이르다. `learning_rate`를 낮추고 `num_leaves`·`min_data_in_leaf`를 조정할 여지가 있다. 계획서 범위 밖이라 손대지 않았다.
2. **타자 x 구종 축 피처** — 현재 타자 피처는 `whiff_rate` 등을 전 구종 평균 4개 스칼라로 압축한다("이 타자가 슬라이더에 약하다"는 가장 예측력 있는 신호가 사라진 상태). 타자×구종 11열로 펴면 개선 여지가 있다. `data/feature_builders.py::build_batter_matchup_features` 참고.
3. Task 9 캘리브레이션 — top-1 자체는 안 오르지만 확률값의 신뢰도가 올라간다.

셋 중 **2번이 가장 유망**하다. 앙상블이 실제로 준 건 +0.42%p뿐이라 여전히 여기가 본류다. 피처 보강이 모델 교체보다 기여가 컸다는 실측(2.6%p vs 1.6%p)과 방향이 맞는다.

## 남은 정리 작업

- `requirements-deploy.txt` 상단 주석이 "프로덕션 추론 경로는 RandomForest만 쓴다(ADR-0001)"로 남아 있다. 실제로는 LightGBM으로 전환됐다. Task 12에서 ADR-0003과 함께 갱신할 것.
- `README.md`의 정확도 수치가 39.5%/78.7% 기준일 수 있다. 확인 필요.
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

# 앱
./venv/bin/python app.py   # http://localhost:7862
```

`data/processed/enriched_*.parquet`와 `next_pitch_dataset_*.csv`는 gitignore 대상이다.
클론 직후에는 위 두 명령을 먼저 돌려야 한다.
