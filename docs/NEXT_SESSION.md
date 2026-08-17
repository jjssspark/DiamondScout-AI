# 다음 세션 인계 (2026-08-17 종료 시점)

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
| **7 GRU** | **부분 완료 — 학습 미실행** | `2bd749e` |
| 8 앙상블 (게이트) | 미착수 | |
| 9 확률 캘리브레이션 | 미착수 | |
| 11 배포 아티팩트 + Render 검증 | 미착수 | |
| 12 문서 + ADR-0003 | 미착수 | |

테스트 53 → **105건**.

## 정확도 현황

| | 시작 | 현재 (서빙 실측) | 목표 |
|---|---|---|---|
| top-1 | 39.5% | **43.25%** | 47% |
| top-3 | 78.7% | **85.56%** | 85% (달성) |

- **top-3는 목표 달성.** top-1이 3.75%p 남았다.
- 모델 크기 188MB → 9.89MB, 추론 23.6ms → 1.73ms.
- 개선분 분해: 피처 보강 top-1 +2.6%p, 모델 교체 +1.6%p.
- 상세는 `docs/PERFORMANCE.md`.

## 1순위: TS-010 해결 — GRU 학습이 교착한다

`./venv/bin/python scripts/train_seq.py`가 parquet 로딩 직후 `model.fit()`에서 멈춘다.
CPU 0%, RSS 112MB, 65분 무변화, **예외 없음**.

확인된 사실:
- 합성 numpy 배열로는 전체 41만 행 1에폭이 **4.9초**에 끝난다 → 데이터 크기·Keras 문제가 아니다.
- `tests/test_seq_infer.py`(Keras 사용) 5건은 4.2초에 통과한다 → Keras 자체는 정상.
- 멈춘 프로세스가 살아 있는 동안 다른 Keras 작업도 같이 멈춘다. `kill -9` 하면 정상 복귀.
- 차이는 **pandas/pyarrow로 parquet를 읽은 뒤 TensorFlow를 쓴다는 것** 하나다.

가설: pyarrow와 TensorFlow의 스레드풀(OpenMP 런타임) 충돌. macOS에서 알려진 계열.

검증 순서 (싼 것부터):
1. parquet를 별도 프로세스에서 `.npy`로 변환해 두고, 학습 프로세스는 pyarrow를 아예 import 하지 않게 분리
2. `OMP_NUM_THREADS=1`, `KMP_DUPLICATE_LIB_OK=TRUE` 환경변수로 실행
3. import 순서 바꾸기 (keras 먼저, pandas 나중)

**주의**: 오래 걸리는 작업을 `| tail`로 감싸면 중간 종료 시 로그가 통째로 사라진다.
`> logfile 2>&1`로 직접 받을 것. 이번 세션에서 두 번 겪었다.

## 2순위: Task 8 앙상블 (게이트)

T7이 끝나야 시작할 수 있다. 게이트: **val에서 단일 모델을 못 이기면 채택하지 않는다.**

기대치는 낮게 잡는 것이 맞다. LightGBM 피처 중요도의 **81%가 prior**인데 GRU는 prior를 전혀 보지 않는다(lag 9개 필드만). 기존 LSTM이 40.7%였으니 GRU도 비슷할 것이고, LightGBM 43.7%를 단독으로 넘기 어렵다.
다만 **틀리는 지점이 다르면** 앙상블이 이길 수 있다. 게이트가 존재하는 이유다.

## top-1 3.75%p를 메울 후보

재랭킹 쪽은 이미 측정했고 여지가 없다(`docs/PERFORMANCE.md`의 "서비스 재랭킹의 기여도" 절). 남은 후보:

1. **LightGBM 하이퍼파라미터** — `best_iteration=89`로 조기 수렴했다. 2000라운드를 허용했는데 89에서 멈춘 건 이례적으로 이르다. `learning_rate`를 낮추고 `num_leaves`·`min_data_in_leaf`를 조정할 여지가 있다. 계획서 범위 밖이라 손대지 않았다.
2. **타자 x 구종 축 피처** — 현재 타자 피처는 `whiff_rate` 등을 전 구종 평균 4개 스칼라로 압축한다("이 타자가 슬라이더에 약하다"는 가장 예측력 있는 신호가 사라진 상태). 타자×구종 11열로 펴면 개선 여지가 있다. `data/feature_builders.py::build_batter_matchup_features` 참고.
3. Task 9 캘리브레이션 — top-1 자체는 안 오르지만 확률값의 신뢰도가 올라간다.

셋 중 **2번이 가장 유망**하다. 피처 보강이 모델 교체보다 기여가 컸다는 실측(2.6%p vs 1.6%p)과 방향이 맞는다.

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
