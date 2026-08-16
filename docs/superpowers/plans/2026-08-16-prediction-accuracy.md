# 다음 구종 예측 정확도 고도화 구현 계획 (트랙 A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 다음 구종 예측의 top-1 정확도를 39.5% → 47% 이상, top-3를 78.7% → 85% 이상으로 올린다.

**Architecture:** 모델에 없던 "투수 정체성" 신호(아스널 prior·카운트 조건부 prior·타자 매치업)와 시간·피로 피처를 학습 데이터에 추가하고, RandomForest를 LightGBM으로 교체한 뒤, 선택적으로 GRU 시퀀스 모델과 앙상블한다. 서빙 의존성을 늘리지 않기 위해 GRU 가중치는 `.npz`로 내보내 numpy로 추론한다.

**Tech Stack:** Python 3.13, pandas 3.0.3, scikit-learn 1.9.0, LightGBM(신규), Keras 3.15(학습 전용), numpy 2.5.0, pytest 9.1.1

**Spec:** `docs/superpowers/specs/2026-08-15-accuracy-and-dugout-console-design.md`

## Global Constraints

- **누수 금지**: 모든 prior 집계는 train split에서만 수행한다. val/test에는 조인만 한다.
- **train/val/test 분할**: `models/next_pitch_model.py`의 `time_based_split`(game_pk 시간순, 0.7/0.15/0.15)을 그대로 쓴다. 새 split 함수를 만들지 않는다.
- **배포 제약**: Render 무료 티어 512MB RAM. `requirements-deploy.txt`에 TensorFlow·torch·faiss·sentence-transformers·pybaseball을 추가하지 않는다.
- **가상환경**: 모든 명령은 `./venv/bin/python`, `./venv/bin/pytest`로 실행한다. 시스템 python3는 의존성이 맞지 않는다.
- **데이터 연도**: 2025 (`YEAR = 2025`). raw는 `data/raw/statcast_2025_full.csv` (242MB, 존재 확인됨).
- **클래스 수**: 11 (FF, SI, SL, CH, FC, ST, CU, FS, KC, SV, OTHER). 매핑은 `data/processed/pitch_label_mapping.json`.
- **결정 게이트**: LightGBM이 val에서 보강 피처 RF를 못 이기면 RF를 유지한다. 앙상블이 val에서 단일 모델을 못 이기면 앙상블을 채택하지 않는다. 두 경우 모두 근거를 문서에 남긴다.
- **누수 의심 기준**: 어느 단계든 test top-1이 60%를 넘으면 개선이 아니라 누수로 간주하고 중단·점검한다.
- **raw 데이터 불변**: `data/raw/`는 읽기 전용. 절대 수정하지 않는다.

---

### Task 1: 선수 이름 룩업 테이블

Statcast raw의 `player_name`은 **투수 이름만** 담고 있다(검증됨: 투수당 고유 이름 1개, 타자당 7개). 그래서 UI에 타자가 `Batter ID 621566`으로 노출된다. MLBAM ID → 이름 룩업 테이블을 따로 만든다.

**Files:**
- Create: `data/player_names.py`
- Create: `tests/test_player_names.py`
- Modify: `data/preprocess_statcast.py` (`build_batter_matchup_profile`에 이름 조인)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `data/player_names.py::attach_player_names(profile: pd.DataFrame, names: pd.DataFrame, id_col: str) -> pd.DataFrame`
  - `data/player_names.py::build_player_name_table(root: str, year: int) -> pd.DataFrame` — 컬럼 `["player_id", "player_name"]`
  - 산출물 `data/processed/player_names.csv`
  - `batter_matchup_profile_{year}.csv`에 `player_name` 컬럼 추가

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_player_names.py
import pandas as pd

from data.player_names import attach_player_names


def test_attaches_name_for_known_id():
    profile = pd.DataFrame({"batter": [111, 222], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({"player_id": [111, 222], "player_name": ["Kim, A", "Lee, B"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert list(result["player_name"]) == ["Kim, A", "Lee, B"]


def test_falls_back_to_id_label_when_name_missing():
    profile = pd.DataFrame({"batter": [111, 999], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert result.loc[result["batter"] == 999, "player_name"].iloc[0] == "Batter ID 999"


def test_does_not_drop_rows_when_name_missing():
    profile = pd.DataFrame({"batter": [111, 999], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert len(result) == 2
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_player_names.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data.player_names'`

- [ ] **Step 3: 최소 구현 작성**

```python
# data/player_names.py
"""MLBAM player id -> 이름 룩업 테이블.

Statcast raw의 player_name 컬럼은 투수 이름만 담는다(타자 기준으로 보면 그 타자를
상대한 투수들의 이름이 섞여 나온다). 타자 이름은 pybaseball 역조회로 따로 만든다.
"""

import os

import pandas as pd

ID_LABEL_PREFIX = {"batter": "Batter ID", "pitcher": "Pitcher ID"}


def attach_player_names(profile: pd.DataFrame, names: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """profile에 player_name을 좌측 조인한다. 이름을 못 찾으면 'Batter ID {id}'로 채운다."""
    merged = profile.merge(
        names.rename(columns={"player_id": id_col}), on=id_col, how="left"
    )
    prefix = ID_LABEL_PREFIX.get(id_col, "Player ID")
    fallback = prefix + " " + merged[id_col].astype(str)
    merged["player_name"] = merged["player_name"].fillna(fallback)
    return merged


def build_player_name_table(root: str, year: int) -> pd.DataFrame:
    """raw에 등장하는 모든 batter/pitcher id의 이름을 pybaseball로 역조회한다.

    pybaseball은 배포 의존성이 아니라 이 스크립트 실행 시점에만 필요하다.
    """
    from pybaseball import playerid_reverse_lookup

    raw_path = os.path.join(root, "data", "raw", f"statcast_{year}_full.csv")
    ids = pd.read_csv(raw_path, usecols=["batter", "pitcher"])
    all_ids = pd.unique(pd.concat([ids["batter"], ids["pitcher"]]).dropna().astype(int))

    looked_up = playerid_reverse_lookup(list(all_ids), key_type="mlbam")
    table = pd.DataFrame({
        "player_id": looked_up["key_mlbam"].astype(int),
        "player_name": (
            looked_up["name_last"].str.title() + ", " + looked_up["name_first"].str.title()
        ),
    })
    return table.drop_duplicates(subset="player_id").reset_index(drop=True)


if __name__ == "__main__":
    import argparse

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()

    out = build_player_name_table(root, args.year)
    out_path = os.path.join(root, "data", "processed", "player_names.csv")
    out.to_csv(out_path, index=False)
    print(f"[저장] {out_path} ({len(out):,}명)")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_player_names.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 룩업 테이블 실제 생성**

Run: `./venv/bin/python data/player_names.py --year 2025`
Expected: `data/processed/player_names.csv` 생성, 1,000명 이상 출력

확인: `./venv/bin/python -c "import pandas as pd; d=pd.read_csv('data/processed/player_names.csv'); print(len(d)); print(d.head())"`

- [ ] **Step 6: `build_batter_matchup_profile`에 이름 조인**

`data/preprocess_statcast.py`의 `build_batter_matchup_profile`을 교체한다.

```python
def build_batter_matchup_profile(df: pd.DataFrame, name_table: pd.DataFrame | None = None) -> pd.DataFrame:
    g = df.groupby(["batter", "stand", "p_throws", "pitch_label"]).agg(
        pitch_count=("pitch_label", "size"),
        whiff_rate=("is_whiff", "mean"),
        foul_rate=("is_foul", "mean"),
        in_play_rate=("is_in_play", "mean"),
        hard_hit_rate=("hard_hit", "mean"),
        extra_base_hit_rate=("is_extra_base_hit", "mean"),
        avg_delta_run_exp=("delta_run_exp", "mean"),
    ).reset_index()
    if name_table is not None:
        from data.player_names import attach_player_names

        g = attach_player_names(g, name_table, id_col="batter")
    return g.sort_values(["batter", "stand", "p_throws", "pitch_label"]).reset_index(drop=True)
```

`process_year`의 호출부를 바꾼다.

```python
    names_path = os.path.join(processed_dir, "player_names.csv")
    name_table = pd.read_csv(names_path) if os.path.exists(names_path) else None

    outputs = {
        f"next_pitch_dataset_{year}.csv": build_next_pitch_dataset(df),
        f"pitcher_pitch_profile_{year}.csv": build_pitcher_pitch_profile(df),
        f"count_pitch_profile_{year}.csv": build_count_pitch_profile(df),
        f"zone_risk_profile_{year}.csv": build_zone_risk_profile(df),
        f"batter_matchup_profile_{year}.csv": build_batter_matchup_profile(df, name_table),
    }
```

- [ ] **Step 7: 커밋**

```bash
git add data/player_names.py tests/test_player_names.py data/preprocess_statcast.py data/processed/player_names.csv
git commit -m "feat: MLBAM id -> 선수 이름 룩업 테이블 추가

Statcast raw의 player_name은 투수 이름만 담아 타자가 ID로 노출됐다.
pybaseball 역조회로 이름 테이블을 만들고 타자 매치업 프로파일에 조인한다.
이름을 못 찾는 타자는 'Batter ID {id}'로 degrade 한다."
```

---

### Task 2: prior 피처 빌더 — 투수 아스널 · 카운트 조건부 · 타자 매치업

**핵심 누수 위험 구간.** prior는 train split에서만 집계하고 val/test에는 조인만 한다.

**Files:**
- Create: `data/feature_builders.py`
- Create: `tests/test_feature_builders.py`

**Interfaces:**
- Consumes: 없음 (순수 함수 모듈)
- Produces:
  - `PRIOR_SHRINKAGE_K = 20`
  - `league_prior(train_df, label_ids) -> dict[int, float]`
  - `build_pitcher_prior(train_df, label_ids) -> pd.DataFrame` — 컬럼 `["pitcher", "pitcher_prior_0" .. "pitcher_prior_10"]`
  - `build_count_prior(train_df, label_ids, k=20) -> pd.DataFrame` — 컬럼 `["pitcher", "balls", "strikes", "count_prior_0" .. "count_prior_10"]`
  - `build_batter_matchup_features(train_df, raw_profile) -> pd.DataFrame` — 컬럼 `["batter", "batter_whiff_avg", "batter_hardhit_avg", "batter_xbh_avg", "batter_whiff_max"]`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_feature_builders.py
import numpy as np
import pandas as pd
import pytest

from data.feature_builders import (
    PRIOR_SHRINKAGE_K,
    build_batter_matchup_features,
    build_count_prior,
    build_pitcher_prior,
    league_prior,
)

LABEL_IDS = [0, 1, 2]


def _train_df():
    # 투수 100: FF(0) 3개, SL(1) 1개 -> 0.75 / 0.25 / 0.0
    # 투수 200: SL(1) 2개, CU(2) 2개 -> 0.0 / 0.5 / 0.5
    return pd.DataFrame({
        "pitcher": [100, 100, 100, 100, 200, 200, 200, 200],
        "batter":  [10, 10, 11, 11, 12, 12, 13, 13],
        "balls":   [0, 0, 1, 1, 0, 0, 1, 1],
        "strikes": [0, 0, 0, 0, 0, 0, 0, 0],
        "target_pitch_label_id": [0, 0, 0, 1, 1, 1, 2, 2],
    })


def test_pitcher_prior_ratios_sum_to_one():
    result = build_pitcher_prior(_train_df(), LABEL_IDS)
    cols = [f"pitcher_prior_{i}" for i in LABEL_IDS]

    assert np.allclose(result[cols].sum(axis=1), 1.0)


def test_pitcher_prior_reflects_actual_mix():
    result = build_pitcher_prior(_train_df(), LABEL_IDS).set_index("pitcher")

    assert result.loc[100, "pitcher_prior_0"] == pytest.approx(0.75)
    assert result.loc[100, "pitcher_prior_1"] == pytest.approx(0.25)
    assert result.loc[100, "pitcher_prior_2"] == pytest.approx(0.0)


def test_league_prior_is_overall_distribution():
    result = league_prior(_train_df(), LABEL_IDS)

    assert result[0] == pytest.approx(3 / 8)
    assert sum(result.values()) == pytest.approx(1.0)


def test_count_prior_shrinks_toward_pitcher_prior_when_sparse():
    """표본 1개짜리 카운트는 투수 전체 아스널 쪽으로 당겨져야 한다."""
    result = build_count_prior(_train_df(), LABEL_IDS, k=PRIOR_SHRINKAGE_K)
    row = result[(result["pitcher"] == 100) & (result["balls"] == 1) & (result["strikes"] == 0)]

    # 이 카운트의 raw 비율은 FF 0.5인데, 투수 전체 0.75 쪽으로 당겨져야 한다
    assert row["count_prior_0"].iloc[0] > 0.5


def test_count_prior_ratios_sum_to_one():
    result = build_count_prior(_train_df(), LABEL_IDS, k=PRIOR_SHRINKAGE_K)
    cols = [f"count_prior_{i}" for i in LABEL_IDS]

    assert np.allclose(result[cols].sum(axis=1), 1.0)


def _raw_batter_profile():
    return pd.DataFrame({
        "batter": [10, 10, 11, 99],
        "pitch_label": ["FF", "SL", "FF", "FF"],
        "whiff_rate": [0.1, 0.3, 0.2, 0.9],
        "hard_hit_rate": [0.4, 0.2, 0.3, 0.1],
        "extra_base_hit_rate": [0.05, 0.01, 0.02, 0.5],
    })


def test_batter_features_use_only_train_batters():
    """train에 없는 타자 99는 집계에서 빠져야 한다."""
    result = build_batter_matchup_features(_train_df(), _raw_batter_profile())

    assert 99 not in set(result["batter"])


def test_batter_whiff_max_takes_worst_pitch():
    result = build_batter_matchup_features(_train_df(), _raw_batter_profile()).set_index("batter")

    assert result.loc[10, "batter_whiff_max"] == pytest.approx(0.3)
    assert result.loc[10, "batter_whiff_avg"] == pytest.approx(0.2)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_feature_builders.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data.feature_builders'`

- [ ] **Step 3: 최소 구현 작성**

```python
# data/feature_builders.py
"""다음 구종 예측용 prior · 시간 피처 빌더.

모든 prior는 train split에서만 집계한다. 전체 데이터로 집계하면 test 정보가
train으로 새어 들어가 정확도가 비현실적으로 높게 나온다.
"""

import numpy as np
import pandas as pd

TARGET_COL = "target_pitch_label_id"
PRIOR_SHRINKAGE_K = 20


def league_prior(train_df: pd.DataFrame, label_ids: list[int]) -> dict[int, float]:
    """train 전체의 구종 분포. 처음 보는 투수/타자를 채우는 데 쓴다."""
    counts = train_df[TARGET_COL].value_counts()
    total = float(counts.sum())
    return {i: float(counts.get(i, 0)) / total for i in label_ids}


def _ratio_matrix(counts: pd.DataFrame, group_cols: list[str], label_ids: list[int], prefix: str) -> pd.DataFrame:
    """(group_cols, label) 카운트 테이블을 label별 비율 컬럼으로 편다."""
    wide = counts.pivot_table(
        index=group_cols, columns=TARGET_COL, values="n", fill_value=0, aggfunc="sum"
    )
    for i in label_ids:
        if i not in wide.columns:
            wide[i] = 0
    wide = wide[label_ids]
    totals = wide.sum(axis=1).replace(0, np.nan)
    ratios = wide.div(totals, axis=0).fillna(0.0)
    ratios.columns = [f"{prefix}_{i}" for i in label_ids]
    return ratios.reset_index()


def build_pitcher_prior(train_df: pd.DataFrame, label_ids: list[int]) -> pd.DataFrame:
    """투수별 구종 구사 비율 (아스널)."""
    counts = train_df.groupby(["pitcher", TARGET_COL]).size().rename("n").reset_index()
    return _ratio_matrix(counts, ["pitcher"], label_ids, "pitcher_prior")


def build_count_prior(
    train_df: pd.DataFrame, label_ids: list[int], k: int = PRIOR_SHRINKAGE_K
) -> pd.DataFrame:
    """투수 x 볼카운트별 구종 비율.

    3-0 같은 희소 카운트는 표본이 적어 비율이 튄다. 투수 전체 아스널 쪽으로
    shrinkage 스무딩한다: (n*r_count + k*r_pitcher) / (n + k)
    """
    counts = (
        train_df.groupby(["pitcher", "balls", "strikes", TARGET_COL]).size().rename("n").reset_index()
    )
    count_ratios = _ratio_matrix(counts, ["pitcher", "balls", "strikes"], label_ids, "count_prior")

    n_per_count = (
        train_df.groupby(["pitcher", "balls", "strikes"]).size().rename("n_count").reset_index()
    )
    pitcher_ratios = build_pitcher_prior(train_df, label_ids)

    merged = count_ratios.merge(n_per_count, on=["pitcher", "balls", "strikes"]).merge(
        pitcher_ratios, on="pitcher"
    )

    n = merged["n_count"].to_numpy()[:, None]
    raw = merged[[f"count_prior_{i}" for i in label_ids]].to_numpy()
    base = merged[[f"pitcher_prior_{i}" for i in label_ids]].to_numpy()
    smoothed = (n * raw + k * base) / (n + k)

    out = merged[["pitcher", "balls", "strikes"]].copy()
    for idx, i in enumerate(label_ids):
        out[f"count_prior_{i}"] = smoothed[:, idx]
    return out


def build_batter_matchup_features(train_df: pd.DataFrame, raw_profile: pd.DataFrame) -> pd.DataFrame:
    """타자 x 구종 반응 지표를 타자 단위로 요약한다.

    train split에 등장한 타자만 사용한다 — 그래야 누수가 없다.
    raw_profile은 data/processed/batter_matchup_profile_{year}.csv 형식이다.
    """
    train_batters = set(train_df["batter"].unique())
    prof = raw_profile[raw_profile["batter"].isin(train_batters)]
    return prof.groupby("batter").agg(
        batter_whiff_avg=("whiff_rate", "mean"),
        batter_hardhit_avg=("hard_hit_rate", "mean"),
        batter_xbh_avg=("extra_base_hit_rate", "mean"),
        batter_whiff_max=("whiff_rate", "max"),
    ).reset_index()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_feature_builders.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add data/feature_builders.py tests/test_feature_builders.py
git commit -m "feat: 투수 아스널·카운트 조건부·타자 매치업 prior 빌더 추가

현재 모델은 투수 정체성 신호가 전혀 없어 리그 평균 분포를 학습한다.
희소 카운트는 투수 전체 아스널로 shrinkage 스무딩(k=20)한다.
모든 집계는 train split 한정 — 누수 방지."
```

---

### Task 3: 시간 · 피로 피처

현재 데이터셋에 완전히 없는 축이다. 같은 경기 안에서의 누적·순서 정보를 만든다.

**Files:**
- Modify: `data/feature_builders.py`
- Modify: `tests/test_feature_builders.py`

**Interfaces:**
- Consumes: Task 2의 `data/feature_builders.py`
- Produces: `add_temporal_features(df: pd.DataFrame) -> pd.DataFrame` — 아래 6개 컬럼을 추가한 새 DataFrame 반환
  `pitch_of_atbat`, `pitcher_pitch_count_game`, `times_through_order`, `same_pitch_streak`, `prev_pitch_outcome_enc`, `is_first_pitch_of_ab`
- Produces: `OUTCOME_ENC: dict[str, int]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_feature_builders.py` 끝에 추가한다.

```python
from data.feature_builders import add_temporal_features


def _game_df():
    """한 경기, 투수 100. 타석 1(3구) -> 타석 2(2구)."""
    return pd.DataFrame({
        "game_pk": [1, 1, 1, 1, 1],
        "pitcher": [100, 100, 100, 100, 100],
        "batter":  [10, 10, 10, 20, 20],
        "at_bat_number": [1, 1, 1, 2, 2],
        "pitch_number": [1, 2, 3, 1, 2],
        "pitch_label_id_lag1": [np.nan, 0.0, 0.0, 1.0, 0.0],
        "prev_pitch_outcome": ["none", "ball", "ball", "foul", "called_strike"],
    })


def test_pitch_of_atbat_counts_within_at_bat():
    result = add_temporal_features(_game_df())

    assert list(result["pitch_of_atbat"]) == [1, 2, 3, 1, 2]


def test_pitcher_pitch_count_accumulates_across_game():
    result = add_temporal_features(_game_df())

    assert list(result["pitcher_pitch_count_game"]) == [1, 2, 3, 4, 5]


def test_is_first_pitch_of_ab_flags_only_first():
    result = add_temporal_features(_game_df())

    assert list(result["is_first_pitch_of_ab"]) == [1, 0, 0, 1, 0]


def test_times_through_order_increments_on_batter_repeat():
    df = pd.concat([_game_df(), pd.DataFrame({
        "game_pk": [1], "pitcher": [100], "batter": [10],
        "at_bat_number": [3], "pitch_number": [1],
        "pitch_label_id_lag1": [1.0], "prev_pitch_outcome": ["none"],
    })], ignore_index=True)

    result = add_temporal_features(df)

    assert result["times_through_order"].iloc[-1] == 2


def test_same_pitch_streak_counts_consecutive_identical_lags():
    result = add_temporal_features(_game_df())

    # lag1이 [nan, 0, 0, 1, 0] -> 인덱스 2에서 0이 2연속
    assert result["same_pitch_streak"].iloc[2] == 2
    assert result["same_pitch_streak"].iloc[3] == 1


def test_prev_pitch_outcome_is_encoded_as_int():
    result = add_temporal_features(_game_df())

    assert result["prev_pitch_outcome_enc"].dtype.kind in "iu"
    assert result["prev_pitch_outcome_enc"].iloc[0] == 0  # "none"
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_feature_builders.py -v -k "atbat or accumulates or first_pitch or order or streak or outcome"`
Expected: FAIL — `ImportError: cannot import name 'add_temporal_features'`

- [ ] **Step 3: 최소 구현 작성**

`data/feature_builders.py`에 추가한다.

```python
OUTCOME_ENC = {
    "none": 0, "ball": 1, "called_strike": 2, "whiff": 3,
    "foul": 4, "in_play": 5, "hit_by_pitch": 6, "other": 7,
}


def add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """같은 경기 안에서의 누적 · 순서 피처를 추가한다.

    모든 값은 '해당 투구를 던지기 직전'까지의 정보만 쓴다.
    """
    work = df.sort_values(
        ["game_pk", "pitcher", "at_bat_number", "pitch_number"]
    ).reset_index(drop=True).copy()

    by_pitcher = work.groupby(["game_pk", "pitcher"], sort=False)
    by_atbat = work.groupby(["game_pk", "pitcher", "at_bat_number"], sort=False)

    work["pitch_of_atbat"] = by_atbat.cumcount() + 1
    work["is_first_pitch_of_ab"] = (work["pitch_of_atbat"] == 1).astype(int)
    work["pitcher_pitch_count_game"] = by_pitcher.cumcount() + 1

    # 타순 순회: 같은 (경기, 투수)에서 그 타자를 몇 번째 상대하는가.
    first = work[work["is_first_pitch_of_ab"] == 1].copy()
    first["tto"] = first.groupby(["game_pk", "pitcher", "batter"]).cumcount() + 1
    work = work.merge(
        first[["game_pk", "pitcher", "at_bat_number", "tto"]],
        on=["game_pk", "pitcher", "at_bat_number"],
        how="left",
    )
    work["times_through_order"] = work["tto"].fillna(1).astype(int)
    work = work.drop(columns=["tto"])

    # 같은 구종 연속 횟수: lag1이 직전 행과 같고 같은 (경기, 투수)면 누적.
    lag1 = work["pitch_label_id_lag1"].to_numpy()
    key = list(zip(work["game_pk"], work["pitcher"]))
    streak = np.ones(len(work), dtype=int)
    for i in range(1, len(work)):
        same_pitcher = key[i] == key[i - 1]
        same_value = lag1[i] == lag1[i - 1] and not np.isnan(lag1[i])
        streak[i] = streak[i - 1] + 1 if (same_pitcher and same_value) else 1
    work["same_pitch_streak"] = streak

    work["prev_pitch_outcome_enc"] = (
        work["prev_pitch_outcome"].map(OUTCOME_ENC).fillna(OUTCOME_ENC["other"]).astype(int)
    )
    return work
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_feature_builders.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: 커밋**

```bash
git add data/feature_builders.py tests/test_feature_builders.py
git commit -m "feat: 시간·피로 피처 6종 추가

타석 내 투구수, 경기 누적 투구수, 타순 순회, 같은 구종 연속,
직전 투구 결과, 초구 여부. 현재 데이터셋에 없던 축이다."
```

---

### Task 4: 데이터셋 빌드 파이프라인 통합 + 누수 회귀 테스트

**이 태스크가 계획 전체에서 가장 위험하다.** prior 조인이 잘못되면 정확도가 가짜로 뛴다.

**Files:**
- Create: `data/build_enriched_dataset.py`
- Create: `tests/test_no_leakage.py`
- Modify: `data/preprocess_statcast.py` (`build_next_pitch_dataset`에 `prev_pitch_outcome` 추가)

**Interfaces:**
- Consumes: Task 2·3의 `data/feature_builders.py`, `models/next_pitch_model.py::{load_dataset, time_based_split, TARGET_COL}`
- Produces:
  - `attach_priors(target_df, train_df, label_ids, batter_profile=None) -> pd.DataFrame`
  - `build_enriched_splits(root, year) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]`
  - 산출물 `data/processed/enriched_{train,val,test}_{year}.parquet`

- [ ] **Step 1: 누수 회귀 테스트 작성**

```python
# tests/test_no_leakage.py
"""prior 피처가 미래 데이터를 참조하지 않는지 검증한다.

이 테스트가 깨지면 이 계획의 정확도 개선 수치를 전부 믿을 수 없다.
"""
import pandas as pd
import pytest

from data.build_enriched_dataset import attach_priors
from data.feature_builders import league_prior

LABEL_IDS = [0, 1, 2]


def _train():
    return pd.DataFrame({
        "pitcher": [100, 100, 100, 100],
        "batter": [10, 10, 11, 11],
        "balls": [0, 0, 0, 0], "strikes": [0, 0, 0, 0],
        "target_pitch_label_id": [0, 0, 0, 1],
    })


def test_prior_computed_from_train_only_ignores_test_rows():
    """test에만 존재하는 구종은 prior에 반영되면 안 된다."""
    train = pd.DataFrame({
        "pitcher": [100, 100], "batter": [10, 10],
        "balls": [0, 0], "strikes": [0, 0],
        "target_pitch_label_id": [0, 0],
    })
    test = pd.DataFrame({
        "pitcher": [100, 100], "batter": [10, 10],
        "balls": [0, 0], "strikes": [0, 0],
        "target_pitch_label_id": [2, 2],
    })

    result = attach_priors(test, train, LABEL_IDS)

    assert result["pitcher_prior_0"].iloc[0] == pytest.approx(1.0)
    assert result["pitcher_prior_2"].iloc[0] == pytest.approx(0.0)


def test_unseen_pitcher_falls_back_to_league_prior():
    train = _train()
    test = pd.DataFrame({
        "pitcher": [999], "batter": [10], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, train, LABEL_IDS)
    lg = league_prior(train, LABEL_IDS)

    assert result["pitcher_prior_0"].iloc[0] == pytest.approx(lg[0])


def test_attach_priors_never_drops_rows():
    test = pd.DataFrame({
        "pitcher": [100, 999, 888], "batter": [10, 11, 12],
        "balls": [0, 1, 2], "strikes": [0, 0, 0],
        "target_pitch_label_id": [0, 1, 2],
    })

    result = attach_priors(test, _train(), LABEL_IDS)

    assert len(result) == 3


def test_prior_columns_have_no_nan():
    test = pd.DataFrame({
        "pitcher": [100, 999], "batter": [10, 77],
        "balls": [0, 3], "strikes": [0, 2],
        "target_pitch_label_id": [0, 1],
    })

    result = attach_priors(test, _train(), LABEL_IDS)
    prior_cols = [c for c in result.columns if c.startswith(("pitcher_prior_", "count_prior_"))]

    assert not result[prior_cols].isna().any().any()


def test_batter_features_fall_back_to_train_mean_for_unseen_batter():
    profile = pd.DataFrame({
        "batter": [10, 11],
        "whiff_rate": [0.1, 0.3],
        "hard_hit_rate": [0.4, 0.2],
        "extra_base_hit_rate": [0.05, 0.01],
    })
    test = pd.DataFrame({
        "pitcher": [100], "batter": [777], "balls": [0], "strikes": [0],
        "target_pitch_label_id": [0],
    })

    result = attach_priors(test, _train(), LABEL_IDS, batter_profile=profile)

    assert not result["batter_whiff_avg"].isna().any()
    # train 타자 평균 (0.1 + 0.3) / 2
    assert result["batter_whiff_avg"].iloc[0] == pytest.approx(0.2)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_no_leakage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'data.build_enriched_dataset'`

- [ ] **Step 3: 최소 구현 작성**

```python
# data/build_enriched_dataset.py
"""보강 피처가 붙은 train/val/test split을 만든다.

prior는 반드시 train split에서만 집계한다. 전체로 집계하면 누수다.
"""

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.feature_builders import (
    add_temporal_features,
    build_batter_matchup_features,
    build_count_prior,
    build_pitcher_prior,
    league_prior,
)
from models.next_pitch_model import load_dataset, time_based_split

BATTER_FEATURE_COLS = [
    "batter_whiff_avg", "batter_hardhit_avg", "batter_xbh_avg", "batter_whiff_max",
]


def attach_priors(
    target_df: pd.DataFrame,
    train_df: pd.DataFrame,
    label_ids: list[int],
    batter_profile: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """train에서 집계한 prior를 target_df에 조인한다.

    처음 보는 투수/카운트/타자는 리그 평균(또는 train 평균)으로 채운다.
    행은 절대 드롭하지 않는다.
    """
    pitcher_prior = build_pitcher_prior(train_df, label_ids)
    count_prior = build_count_prior(train_df, label_ids)
    lg = league_prior(train_df, label_ids)

    out = target_df.merge(pitcher_prior, on="pitcher", how="left")
    out = out.merge(count_prior, on=["pitcher", "balls", "strikes"], how="left")

    for i in label_ids:
        out[f"pitcher_prior_{i}"] = out[f"pitcher_prior_{i}"].fillna(lg[i])
        # 카운트 prior가 없으면 그 투수의 아스널로 (그것도 없었으면 이미 리그 평균)
        out[f"count_prior_{i}"] = out[f"count_prior_{i}"].fillna(out[f"pitcher_prior_{i}"])

    if batter_profile is not None:
        batter_feats = build_batter_matchup_features(train_df, batter_profile)
        out = out.merge(batter_feats, on="batter", how="left")
        for col in BATTER_FEATURE_COLS:
            out[col] = out[col].fillna(batter_feats[col].mean())
    return out


def build_enriched_splits(root: str, year: int):
    df = load_dataset(root, year)

    mapping_path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        label_ids = sorted(int(k) for k in json.load(f)["id_to_label"])

    profile_path = os.path.join(root, "data", "processed", f"batter_matchup_profile_{year}.csv")
    batter_profile = pd.read_csv(profile_path) if os.path.exists(profile_path) else None

    df = add_temporal_features(df)
    train_df, val_df, test_df = time_based_split(df)

    return tuple(
        attach_priors(split, train_df, label_ids, batter_profile)
        for split in (train_df, val_df, test_df)
    )


if __name__ == "__main__":
    import argparse

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()

    train, val, test = build_enriched_splits(root, args.year)
    out_dir = os.path.join(root, "data", "processed")
    for name, split in (("train", train), ("val", val), ("test", test)):
        path = os.path.join(out_dir, f"enriched_{name}_{args.year}.parquet")
        split.to_parquet(path, index=False)
        print(f"[저장] {path} ({len(split):,}행 x {len(split.columns)}열)")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_no_leakage.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: `prev_pitch_outcome` 컬럼을 데이터셋에 포함**

`data/preprocess_statcast.py`의 `build_next_pitch_dataset`에서, `work["target_pitch_label_id"] = work["pitch_label_id"]` 바로 위에 추가한다.

```python
    work["prev_pitch_outcome"] = grouped["pitch_result_group"].shift(1).fillna("none")
```

그리고 `out_cols`를 수정한다.

```python
    out_cols = (
        id_cols + current_context_cols + lag_feature_cols
        + ["prev_pitch_outcome", "target_pitch_label_id"]
    )
```

- [ ] **Step 6: 전처리 재실행 + 보강 split 생성**

Run: `./venv/bin/python data/preprocess_statcast.py --year 2025`
Expected: `next_pitch_dataset_2025.csv` 재생성 (약 59만 행)

Run: `./venv/bin/python data/build_enriched_dataset.py --year 2025`
Expected: `enriched_{train,val,test}_2025.parquet` 3개 생성

- [ ] **Step 7: 피처 개수 확인**

Run:
```bash
./venv/bin/python -c "
import pandas as pd
d = pd.read_parquet('data/processed/enriched_train_2025.parquet')
priors = [c for c in d.columns if c.startswith(('pitcher_prior_','count_prior_'))]
temporal = [c for c in d.columns if c in ('pitch_of_atbat','pitcher_pitch_count_game','times_through_order','same_pitch_streak','prev_pitch_outcome_enc','is_first_pitch_of_ab')]
batter = [c for c in d.columns if c.startswith('batter_')]
print('prior', len(priors), '/ temporal', len(temporal), '/ batter', len(batter), '/ 전체', len(d.columns))
print('NaN 있는 컬럼:', d.columns[d.isna().any()].tolist())
"
```
Expected: prior 22개(11+11), temporal 6개, batter 4개. NaN 컬럼 목록이 비어 있어야 한다.

- [ ] **Step 8: 커밋**

```bash
git add data/build_enriched_dataset.py tests/test_no_leakage.py data/preprocess_statcast.py
git commit -m "feat: 보강 피처 데이터셋 빌드 파이프라인 + 누수 회귀 테스트

prior를 train split에서만 집계해 val/test에 조인한다.
처음 보는 투수/타자는 리그 평균으로 채우고 행은 드롭하지 않는다.
누수 회귀 테스트가 이 계획의 정확도 수치 전체를 지탱한다."
```

---

### Task 5: 보강 피처 효과 측정 (동일 조건 RF 비교) — **게이트**

모델을 바꾸기 전에 **피처만의 기여분**을 분리 측정한다. 여기서 안 오르면 조인에 버그가 있다.

**Files:**
- Create: `scripts/eval_feature_gain.py`

**Interfaces:**
- Consumes: Task 4의 enriched parquet
- Produces: `output/metrics/feature_gain_2025.json` — 키 `baseline_top1`, `baseline_top3`, `enriched_top1`, `enriched_top3`, `delta_top1`, `delta_top3`, `n_features_baseline`, `n_features_enriched`, `n_test`

- [ ] **Step 1: 평가 스크립트 작성**

```python
# scripts/eval_feature_gain.py
"""보강 피처의 순수 기여분을 측정한다.

같은 split · 같은 모델(RandomForest)로 기존 피처 vs 보강 피처를 비교한다.
모델 교체(LightGBM) 효과와 섞이지 않게 이 단계를 따로 둔다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import top_k_accuracy_score

from models.next_pitch_model import ID_COLS, RANDOM_STATE, TARGET_COL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025
EXCLUDE = set(ID_COLS) | {TARGET_COL, "prev_pitch_outcome"}
NEW_PREFIXES = ("pitcher_prior_", "count_prior_", "batter_")
NEW_TEMPORAL = {
    "pitch_of_atbat", "pitcher_pitch_count_game", "times_through_order",
    "same_pitch_streak", "prev_pitch_outcome_enc", "is_first_pitch_of_ab",
}


def _is_new(col: str) -> bool:
    return col.startswith(NEW_PREFIXES) or col in NEW_TEMPORAL


def _evaluate(train, test, feature_cols):
    model = RandomForestClassifier(
        n_estimators=150, max_depth=16, min_samples_leaf=30,
        n_jobs=-1, random_state=RANDOM_STATE,
    )
    model.fit(train[feature_cols], train[TARGET_COL])
    proba = model.predict_proba(test[feature_cols])
    y = test[TARGET_COL]
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=model.classes_)),
        float(top_k_accuracy_score(y, proba, k=3, labels=model.classes_)),
    )


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    train = pd.read_parquet(os.path.join(processed, f"enriched_train_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    all_cols = [c for c in train.columns if c not in EXCLUDE]
    baseline_cols = [c for c in all_cols if not _is_new(c)]

    print(f"[기존] {len(baseline_cols)}피처로 학습 중...")
    b1, b3 = _evaluate(train, test, baseline_cols)
    print(f"[기존] top1={b1:.4f} top3={b3:.4f}")

    print(f"[보강] {len(all_cols)}피처로 학습 중...")
    e1, e3 = _evaluate(train, test, all_cols)
    print(f"[보강] top1={e1:.4f} top3={e3:.4f}")

    result = {
        "n_features_baseline": len(baseline_cols),
        "n_features_enriched": len(all_cols),
        "baseline_top1": b1, "baseline_top3": b3,
        "enriched_top1": e1, "enriched_top3": e3,
        "delta_top1": e1 - b1, "delta_top3": e3 - b3,
        "n_test": int(len(test)),
    }
    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"feature_gain_{YEAR}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[델타] top1 {result['delta_top1']:+.4f} / top3 {result['delta_top3']:+.4f}")
    print(f"[저장] {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실행**

Run: `./venv/bin/python scripts/eval_feature_gain.py`
Expected: 두 모델 학습 후 델타 출력. 소요 시간을 기록한다.

- [ ] **Step 3: 게이트 판정**

| 결과 | 조치 |
|---|---|
| `delta_top1 >= +0.05` | 통과. Task 6으로 진행 |
| `0 < delta_top1 < 0.05` | shrinkage k값·조인 점검 후 재측정. 그래도 미달이면 사용자에게 보고하고 판단을 구한다 |
| `enriched_top1 > 0.60` | **누수 의심.** 중단하고 `tests/test_no_leakage.py` 확장, `attach_priors` 재검토 |
| `delta_top1 <= 0` | 중단. 조인 로직에 버그가 있다 |

- [ ] **Step 4: 커밋**

```bash
git add scripts/eval_feature_gain.py output/metrics/feature_gain_2025.json
git commit -m "test: 보강 피처 기여분 측정 (동일 split · 동일 RF)

모델 교체 효과와 섞이지 않게 피처 기여분만 분리 측정한다."
```

---

### Task 6: LightGBM 전환

**Files:**
- Create: `models/lgbm_next_pitch.py`
- Create: `tests/test_lgbm_model.py`
- Create: `scripts/train_lgbm.py`
- Modify: `requirements.txt`, `requirements-deploy.txt`

**Interfaces:**
- Consumes: Task 4의 enriched parquet
- Produces:
  - `models/lgbm_next_pitch.py::FEATURE_EXCLUDE: set[str]`
  - `get_feature_columns(df) -> list[str]`
  - `train_lgbm(train_df, val_df, feature_cols, num_class=11, params=None, num_boost_round=2000) -> lgb.Booster`
  - `predict_proba(booster, X) -> np.ndarray` — shape `(n, num_class)`
  - `save_model(booster, feature_cols, root, suffix="") -> str`
  - 아티팩트 `models/next_pitch_lgbm.txt`, `models/next_pitch_lgbm_features.json`, `output/metrics/lgbm_metrics_2025.json`

- [ ] **Step 1: LightGBM 설치**

```bash
./venv/bin/pip install lightgbm==4.7.0
./venv/bin/python -c "import lightgbm; print(lightgbm.__version__)"
```

import가 실패하면 numpy 2.5.0 / pandas 3.0.3과 호환되는 버전을 찾아 고정하고, 확정 버전을 이 계획서에 기록한다.

`requirements.txt`와 `requirements-deploy.txt` **양쪽에** `lightgbm==4.7.0`을 추가한다. 배포에도 넣는 이유는 이 모델이 프로덕션 추론 경로가 되기 때문이다.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_lgbm_model.py
import numpy as np
import pandas as pd

from models.lgbm_next_pitch import predict_proba, train_lgbm

RNG = np.random.default_rng(0)


def _toy_split(n=400):
    x1 = RNG.normal(size=n)
    # 라벨이 x1에 의존하게 만들어 학습이 실제로 되는지 확인 가능하게 한다
    y = (x1 > 0.5).astype(int) + (x1 > 1.2).astype(int)
    return pd.DataFrame({"x1": x1, "x2": RNG.normal(size=n), "target_pitch_label_id": y})


def test_predict_proba_shape_matches_class_count():
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3)

    assert predict_proba(booster, val[["x1", "x2"]]).shape == (len(val), 3)


def test_probabilities_sum_to_one():
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3)

    proba = predict_proba(booster, val[["x1", "x2"]])

    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_learns_signal_better_than_random():
    train, val = _toy_split(), _toy_split(200)
    booster = train_lgbm(train, val, ["x1", "x2"], num_class=3)

    proba = predict_proba(booster, val[["x1", "x2"]])
    acc = (proba.argmax(axis=1) == val["target_pitch_label_id"]).mean()

    assert acc > 0.5
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_lgbm_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models.lgbm_next_pitch'`

- [ ] **Step 4: 최소 구현 작성**

```python
# models/lgbm_next_pitch.py
"""다음 구종 예측 LightGBM 모델.

RandomForest 대비 선택 이유:
- 크기: RF 프로덕션 모델이 188MB인 반면 LightGBM은 수 MB 수준이다.
  Render 무료 티어(512MB) 제약이 풀린다.
- 정확도: 표 형태 다중분류에서 GBDT가 RF보다 일반적으로 우세하다.
"""

import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

from models.next_pitch_model import ID_COLS, RANDOM_STATE, TARGET_COL

FEATURE_EXCLUDE = set(ID_COLS) | {TARGET_COL, "prev_pitch_outcome"}

DEFAULT_PARAMS = {
    "objective": "multiclass",
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 96,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": RANDOM_STATE,
    "num_threads": -1,
    "verbosity": -1,
}


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in FEATURE_EXCLUDE]


def train_lgbm(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    feature_cols: list[str],
    num_class: int = 11,
    params: dict | None = None,
    num_boost_round: int = 2000,
) -> lgb.Booster:
    merged = {**DEFAULT_PARAMS, "num_class": num_class, **(params or {})}
    train_set = lgb.Dataset(train_df[feature_cols], label=train_df[TARGET_COL])
    val_set = lgb.Dataset(val_df[feature_cols], label=val_df[TARGET_COL], reference=train_set)

    return lgb.train(
        merged,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)],
    )


def predict_proba(booster: lgb.Booster, X: pd.DataFrame) -> np.ndarray:
    return booster.predict(X, num_iteration=booster.best_iteration)


def save_model(booster: lgb.Booster, feature_cols: list[str], root: str, suffix: str = "") -> str:
    model_path = os.path.join(root, "models", f"next_pitch_lgbm{suffix}.txt")
    booster.save_model(model_path, num_iteration=booster.best_iteration)

    features_path = os.path.join(root, "models", f"next_pitch_lgbm{suffix}_features.json")
    with open(features_path, "w", encoding="utf-8") as f:
        json.dump({"feature_cols": feature_cols}, f, ensure_ascii=False, indent=2)
    return model_path
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_lgbm_model.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 학습 스크립트 작성**

```python
# scripts/train_lgbm.py
"""보강 피처 데이터로 LightGBM을 학습하고 val/test 성능·모델 크기를 기록한다."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from sklearn.metrics import top_k_accuracy_score

from models.lgbm_next_pitch import get_feature_columns, predict_proba, save_model, train_lgbm
from models.next_pitch_model import TARGET_COL

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025


def _topk(y, proba, labels):
    return (
        float(top_k_accuracy_score(y, proba, k=1, labels=labels)),
        float(top_k_accuracy_score(y, proba, k=3, labels=labels)),
    )


def main() -> None:
    processed = os.path.join(ROOT, "data", "processed")
    train = pd.read_parquet(os.path.join(processed, f"enriched_train_{YEAR}.parquet"))
    val = pd.read_parquet(os.path.join(processed, f"enriched_val_{YEAR}.parquet"))
    test = pd.read_parquet(os.path.join(processed, f"enriched_test_{YEAR}.parquet"))

    feature_cols = get_feature_columns(train)
    labels = sorted(train[TARGET_COL].unique())
    print(f"[학습] {len(feature_cols)}피처 / {len(labels)}클래스 / train {len(train):,}행")

    started = time.perf_counter()
    booster = train_lgbm(train, val, feature_cols, num_class=len(labels))
    elapsed = time.perf_counter() - started
    print(f"[학습] 완료 {elapsed:.1f}s / best_iteration={booster.best_iteration}")

    v1, v3 = _topk(val[TARGET_COL], predict_proba(booster, val[feature_cols]), labels)
    t1, t3 = _topk(test[TARGET_COL], predict_proba(booster, test[feature_cols]), labels)
    print(f"[검증] top1={v1:.4f} top3={v3:.4f}")
    print(f"[테스트] top1={t1:.4f} top3={t3:.4f}")

    path = save_model(booster, feature_cols, ROOT)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"[저장] {path} ({size_mb:.2f}MB)")

    out_dir = os.path.join(ROOT, "output", "metrics")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"lgbm_metrics_{YEAR}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "n_features": len(feature_cols), "best_iteration": booster.best_iteration,
            "train_seconds": elapsed, "model_size_mb": size_mb,
            "validation": {"top1_accuracy": v1, "top3_accuracy": v3, "n_samples": len(val)},
            "test": {"top1_accuracy": t1, "top3_accuracy": t3, "n_samples": len(test)},
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
```

Run: `./venv/bin/python scripts/train_lgbm.py`

- [ ] **Step 7: 게이트 판정**

`output/metrics/lgbm_metrics_2025.json`의 val top-1을 Task 5의 `enriched_top1`과 비교한다.

- **LightGBM val top-1 > 보강 RF**: 채택. Task 7로 진행
- **못 이김**: LightGBM을 폐기하고 보강 피처 RF를 프로덕션으로 유지한다. `docs/PERFORMANCE.md`에 시도와 결과를 기록하고 Task 7로 진행(앙상블 베이스가 RF가 됨)

- [ ] **Step 8: 커밋**

```bash
git add models/lgbm_next_pitch.py tests/test_lgbm_model.py scripts/train_lgbm.py \
        requirements.txt requirements-deploy.txt \
        models/next_pitch_lgbm.txt models/next_pitch_lgbm_features.json \
        output/metrics/lgbm_metrics_2025.json
git commit -m "feat: 다음 구종 예측 모델을 LightGBM으로 전환

RF 대비 모델 크기가 크게 줄어 Render 512MB 제약이 풀린다.
early stopping은 val multi_logloss 기준."
```

---

### Task 7: GRU 시퀀스 모델 + numpy 내보내기

**Files:**
- Create: `models/seq_next_pitch.py` (Keras 학습)
- Create: `models/seq_infer.py` (numpy 추론)
- Create: `tests/test_seq_infer.py`
- Create: `scripts/train_seq.py`

**Interfaces:**
- Consumes: Task 4의 enriched parquet
- Produces:
  - `models/seq_next_pitch.py::SEQ_LEN = 5`
  - `models/seq_next_pitch.py::build_model(seq_len, n_features, n_classes, units=64)`
  - `models/seq_next_pitch.py::export_weights(model, npz_path: str) -> None`
  - `models/seq_infer.py::SeqPredictor(npz_path: str)` / `.predict_proba(seq: np.ndarray) -> np.ndarray` — 입력 `(batch, seq_len, n_feat)`, 출력 `(batch, n_classes)`
  - 아티팩트 `models/seq_model_weights.npz`, `output/metrics/seq_metrics_2025.json`

**왜 numpy 내보내기인가**: TensorFlow는 설치 용량만 수백 MB라 `requirements-deploy.txt`에 넣을 수 없다. GRU 순전파는 행렬곱과 시그모이드/탄젠트뿐이라 numpy로 구현 가능하다. 학습은 Keras, 서빙은 numpy로 분리한다.

**시퀀스 길이**: 현재 데이터셋의 lag는 5개까지다. `LOOKBACK`을 8로 늘리려면 59만 행 전처리를 다시 돌려야 하므로 **seq_len=5로 시작**하고, val 성능을 보고 확대 여부를 판단한다.

- [ ] **Step 1: numpy 추론 테스트 작성 (Keras 대조)**

```python
# tests/test_seq_infer.py
"""numpy GRU 순전파가 Keras 출력과 일치하는지 검증한다.

이 테스트가 없으면 서빙 경로가 조용히 틀린 확률을 낼 수 있다.
"""
import numpy as np
import pytest

from models.seq_infer import SeqPredictor

pytest.importorskip("keras", reason="학습 전용 의존성 — 배포 환경에는 없음")

SEQ_LEN, N_FEAT, N_CLASS = 5, 6, 11


@pytest.fixture
def trained_pair(tmp_path):
    """작은 Keras GRU를 만들고 npz로 내보낸 뒤 (keras_model, SeqPredictor)를 돌려준다."""
    from models.seq_next_pitch import build_model, export_weights

    model = build_model(seq_len=SEQ_LEN, n_features=N_FEAT, n_classes=N_CLASS, units=16)
    npz_path = tmp_path / "w.npz"
    export_weights(model, str(npz_path))
    return model, SeqPredictor(str(npz_path))


def test_numpy_matches_keras_output(trained_pair):
    model, predictor = trained_pair
    x = np.random.default_rng(0).normal(size=(4, SEQ_LEN, N_FEAT)).astype("float32")

    keras_out = model.predict(x, verbose=0)
    numpy_out = predictor.predict_proba(x)

    assert np.allclose(keras_out, numpy_out, atol=1e-5)


def test_output_shape(trained_pair):
    _, predictor = trained_pair
    x = np.zeros((3, SEQ_LEN, N_FEAT), dtype="float32")

    assert predictor.predict_proba(x).shape == (3, N_CLASS)


def test_probabilities_sum_to_one(trained_pair):
    _, predictor = trained_pair
    x = np.random.default_rng(1).normal(size=(5, SEQ_LEN, N_FEAT)).astype("float32")

    assert np.allclose(predictor.predict_proba(x).sum(axis=1), 1.0, atol=1e-6)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_seq_infer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models.seq_infer'`

- [ ] **Step 3: Keras 학습 모듈 구현**

```python
# models/seq_next_pitch.py
"""GRU 시퀀스 모델 — 학습 전용 (Keras).

LSTM이 아니라 GRU를 쓰는 이유: 게이트가 3개(LSTM 4개)라 파라미터가 약 25% 적고
numpy 순전파 구현도 짧다. 이 규모에서 두 구조의 성능 차이는 통상 미미하다.
성능이 기존 LSTM보다 떨어지면 LSTM으로 되돌린다.
"""

import numpy as np

SEQ_LEN = 5


def build_model(seq_len: int, n_features: int, n_classes: int, units: int = 64):
    from keras import layers, models

    return models.Sequential([
        layers.Input(shape=(seq_len, n_features)),
        layers.GRU(units, name="gru"),
        layers.Dense(n_classes, activation="softmax", name="out"),
    ])


def export_weights(model, npz_path: str) -> None:
    """Keras GRU/Dense 가중치를 numpy 추론용 npz로 내보낸다.

    Keras GRU는 reset_after=True가 기본이라 recurrent bias가 따로 존재해
    bias 배열 shape이 (2, 3*units)가 된다. seq_infer.py가 이 규약을 따른다.
    """
    gru = model.get_layer("gru")
    dense = model.get_layer("out")
    w_x, w_h, bias = (np.asarray(w) for w in gru.get_weights())
    dense_w, dense_b = (np.asarray(w) for w in dense.get_weights())

    np.savez(
        npz_path,
        gru_kernel=w_x, gru_recurrent=w_h, gru_bias=bias,
        dense_kernel=dense_w, dense_bias=dense_b,
    )
```

- [ ] **Step 4: numpy 추론 모듈 구현**

```python
# models/seq_infer.py
"""GRU 순전파 numpy 구현 — 서빙 전용.

TensorFlow는 설치 용량이 수백 MB라 Render 무료 티어에 올릴 수 없다.
학습은 Keras로 하고 가중치만 npz로 받아 여기서 추론한다.
Keras GRU의 reset_after=True 규약을 따른다.
"""

import numpy as np


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _softmax(x: np.ndarray) -> np.ndarray:
    shifted = x - x.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


class SeqPredictor:
    def __init__(self, npz_path: str):
        w = np.load(npz_path)
        self.w_x = w["gru_kernel"]        # (n_feat, 3u)
        self.w_h = w["gru_recurrent"]     # (u, 3u)
        self.bias = w["gru_bias"]         # (2, 3u) — reset_after=True
        self.dense_w = w["dense_kernel"]
        self.dense_b = w["dense_bias"]
        self.units = self.w_h.shape[0]

    def predict_proba(self, seq: np.ndarray) -> np.ndarray:
        """seq: (batch, seq_len, n_features) -> (batch, n_classes)"""
        x = np.asarray(seq, dtype=np.float64)
        batch = x.shape[0]
        u = self.units
        b_x, b_h = self.bias[0], self.bias[1]

        h = np.zeros((batch, u), dtype=np.float64)
        for t in range(x.shape[1]):
            mat_x = x[:, t, :] @ self.w_x + b_x
            mat_h = h @ self.w_h + b_h

            z = _sigmoid(mat_x[:, :u] + mat_h[:, :u])
            r = _sigmoid(mat_x[:, u:2 * u] + mat_h[:, u:2 * u])
            # reset_after=True: reset gate를 recurrent 행렬곱 '이후'에 곱한다
            n = np.tanh(mat_x[:, 2 * u:] + r * mat_h[:, 2 * u:])
            h = z * h + (1.0 - z) * n

        return _softmax(h @ self.dense_w + self.dense_b)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_seq_infer.py -v`
Expected: PASS (3 passed)

`test_numpy_matches_keras_output`가 실패하면 게이트 순서(z/r/n)나 `reset_after` 규약이 어긋난 것이다. Keras 소스의 `GRUCell.call`을 열어 순서를 맞춘다.

- [ ] **Step 6: 실제 시퀀스 학습 실행**

`scripts/train_seq.py`로 enriched parquet의 lag 컬럼을 `(n, 5, n_feat)` 시퀀스로 재구성해 학습하고, `models/seq_model_weights.npz`와 `output/metrics/seq_metrics_2025.json`(val/test top-1·top-3)을 저장한다.

시퀀스 피처는 lag별로 묶는다: `t=0`이 lag5(가장 오래됨), `t=4`가 lag1(직전). 각 시점의 피처는 `[pitch_label_id, release_speed, pfx_x, pfx_z, plate_x, plate_z, zone_cell, balls, strikes]` 중 사용할 것을 고르며, 학습 전에 표준화한다(평균·표준편차를 npz에 함께 저장해 서빙에서 동일 적용).

- [ ] **Step 7: 커밋**

```bash
git add models/seq_next_pitch.py models/seq_infer.py tests/test_seq_infer.py \
        scripts/train_seq.py models/seq_model_weights.npz output/metrics/seq_metrics_2025.json
git commit -m "feat: GRU 시퀀스 모델 + numpy 서빙 내보내기

TensorFlow를 배포 의존성에 넣지 않기 위해 학습(Keras)과 추론(numpy)을 분리한다.
numpy 순전파는 Keras 출력과 1e-5 이내 일치를 테스트로 보장한다."
```

---

### Task 8: 앙상블 — **게이트**

**Files:**
- Create: `models/ensemble.py`
- Create: `tests/test_ensemble.py`
- Create: `scripts/tune_ensemble.py`

**Interfaces:**
- Consumes: Task 6의 `predict_proba`, Task 7의 `SeqPredictor`
- Produces:
  - `models/ensemble.py::WEIGHT_GRID`
  - `blend(p_a, p_b, w: float) -> np.ndarray`
  - `search_best_weight(p_a, p_b, y, labels) -> tuple[float, float]` — (best_w, best_top1)
  - 아티팩트 `models/ensemble_config.json` — 키 `weight`, `val_top1`, `single_val_top1`, `adopted`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_ensemble.py
import numpy as np
import pytest

from models.ensemble import blend, search_best_weight


def test_blend_sums_to_one():
    p_a = np.array([[0.7, 0.2, 0.1], [0.1, 0.8, 0.1]])
    p_b = np.array([[0.3, 0.3, 0.4], [0.5, 0.2, 0.3]])

    assert np.allclose(blend(p_a, p_b, w=0.6).sum(axis=1), 1.0)


def test_weight_one_returns_first_model_only():
    p_a = np.array([[0.7, 0.2, 0.1]])
    p_b = np.array([[0.1, 0.1, 0.8]])

    assert np.allclose(blend(p_a, p_b, w=1.0), p_a)


def test_weight_zero_returns_second_model_only():
    p_a = np.array([[0.7, 0.2, 0.1]])
    p_b = np.array([[0.1, 0.1, 0.8]])

    assert np.allclose(blend(p_a, p_b, w=0.0), p_b)


def test_search_picks_weight_favoring_better_model():
    """모델 A가 정답을 맞히고 B가 틀리면 최적 가중치는 A쪽으로 치우쳐야 한다."""
    y = np.array([0, 0, 0, 0])
    p_a = np.tile([0.9, 0.05, 0.05], (4, 1))
    p_b = np.tile([0.05, 0.9, 0.05], (4, 1))

    best_w, best_top1 = search_best_weight(p_a, p_b, y, labels=[0, 1, 2])

    assert best_w > 0.5
    assert best_top1 == pytest.approx(1.0)
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_ensemble.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models.ensemble'`

- [ ] **Step 3: 최소 구현 작성**

```python
# models/ensemble.py
"""두 모델 확률의 가중 평균 앙상블.

가중치는 val split에서 top-1 기준으로 격자 탐색한다.
앙상블이 단일 모델을 못 이기면 채택하지 않는다 — 복잡도를 공짜로 늘리지 않는다.
"""

import numpy as np
from sklearn.metrics import top_k_accuracy_score

WEIGHT_GRID = np.round(np.arange(0.0, 1.0001, 0.05), 2)


def blend(p_a: np.ndarray, p_b: np.ndarray, w: float) -> np.ndarray:
    """w * p_a + (1-w) * p_b. w=1이면 A만, w=0이면 B만."""
    return w * np.asarray(p_a) + (1.0 - w) * np.asarray(p_b)


def search_best_weight(p_a, p_b, y, labels: list[int]) -> tuple[float, float]:
    """top-1 정확도가 가장 높은 가중치를 찾는다."""
    best_w, best_score = 1.0, -1.0
    for w in WEIGHT_GRID:
        score = top_k_accuracy_score(y, blend(p_a, p_b, float(w)), k=1, labels=labels)
        if score > best_score:
            best_w, best_score = float(w), float(score)
    return best_w, best_score
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_ensemble.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 가중치 탐색 실행 + 게이트 판정**

`scripts/tune_ensemble.py`로 val에서 최적 w를 찾고 test 성능을 측정해 `models/ensemble_config.json`에 쓴다.

판정:
- **앙상블 val top-1 > 단일 LightGBM val top-1**: `adopted: true`. 채택
- **못 이김 또는 `best_w == 1.0`**: `adopted: false`. **앙상블을 채택하지 않는다.** 단일 모델로 서빙하고 `docs/PERFORMANCE.md`에 "앙상블 시도했으나 개선 없음"을 수치와 함께 기록한다

- [ ] **Step 6: 커밋**

```bash
git add models/ensemble.py tests/test_ensemble.py scripts/tune_ensemble.py models/ensemble_config.json
git commit -m "feat: LightGBM + GRU 가중 평균 앙상블

가중치는 val top-1 기준 격자 탐색(0~1, 0.05 간격).
단일 모델을 못 이기면 채택하지 않고 근거를 기록한다."
```

---

### Task 9: 확률 캘리브레이션

화면에 "포심 31.7%"를 그대로 표시하므로 확률이 실제 빈도와 맞아야 한다. **캘리브레이션은 top-k 정확도를 바꾸지 않는다** — 목적은 표시 숫자의 정직함이다.

**Files:**
- Create: `models/calibration.py`
- Create: `tests/test_calibration.py`
- Create: `scripts/calibrate_model.py`

**Interfaces:**
- Consumes: Task 6·8의 확률 출력
- Produces:
  - `expected_calibration_error(proba, y, n_bins=15) -> float`
  - `fit_temperature(proba, y) -> float`
  - `apply_temperature(proba, T) -> np.ndarray`
  - 아티팩트 `models/calibration.json` — 키 `method`, `temperature`, `ece_before`, `ece_after`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_calibration.py
import numpy as np
import pytest

from models.calibration import apply_temperature, expected_calibration_error, fit_temperature


def test_ece_is_zero_for_perfectly_calibrated_confident_predictions():
    """항상 100% 확신하고 항상 맞히면 ECE는 0이다."""
    proba = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    y = np.array([0, 0, 1])

    assert expected_calibration_error(proba, y) == pytest.approx(0.0, abs=1e-9)


def test_ece_is_high_for_overconfident_wrong_predictions():
    """항상 100% 확신하는데 항상 틀리면 ECE는 1이다."""
    proba = np.array([[1.0, 0.0], [1.0, 0.0]])
    y = np.array([1, 1])

    assert expected_calibration_error(proba, y) == pytest.approx(1.0, abs=1e-9)


def test_apply_temperature_preserves_argmax():
    """온도 스케일링은 순위를 바꾸지 않는다 -> top-k 정확도가 유지된다."""
    proba = np.array([[0.6, 0.3, 0.1], [0.1, 0.2, 0.7]])

    scaled = apply_temperature(proba, T=2.5)

    assert np.array_equal(scaled.argmax(axis=1), proba.argmax(axis=1))


def test_apply_temperature_output_sums_to_one():
    proba = np.array([[0.6, 0.3, 0.1], [0.1, 0.2, 0.7]])

    assert np.allclose(apply_temperature(proba, T=2.5).sum(axis=1), 1.0)


def test_fit_temperature_softens_overconfident_model():
    """과확신 모델에는 T > 1이 나와야 한다 (확률을 눌러야 하므로)."""
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, size=500)
    proba = np.full((500, 3), 0.01)
    for i, label in enumerate(y):
        proba[i, label if i % 2 == 0 else (label + 1) % 3] = 0.98
    proba = proba / proba.sum(axis=1, keepdims=True)

    assert fit_temperature(proba, y) > 1.0
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'models.calibration'`

- [ ] **Step 3: 최소 구현 작성**

```python
# models/calibration.py
"""확률 캘리브레이션 — 온도 스케일링.

앱이 예측 확률을 화면에 그대로 표시하므로 "31.7%"가 실제 빈도와 맞아야 한다.
온도 스케일링은 순위를 바꾸지 않아 top-k 정확도를 그대로 두면서 확신도만 조정한다.
"""

import numpy as np
from scipy.optimize import minimize_scalar

EPS = 1e-12


def expected_calibration_error(proba: np.ndarray, y: np.ndarray, n_bins: int = 15) -> float:
    """예측 확신도와 실제 정확도의 가중 절대차."""
    proba = np.asarray(proba)
    confidence = proba.max(axis=1)
    correct = (proba.argmax(axis=1) == np.asarray(y)).astype(float)

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (confidence > lo) & (confidence <= hi)
        if lo == 0.0:
            mask |= confidence == 0.0
        if not mask.any():
            continue
        ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(ece)


def apply_temperature(proba: np.ndarray, T: float) -> np.ndarray:
    """확률을 로짓으로 되돌려 T로 나눈 뒤 다시 softmax 한다."""
    logits = np.log(np.clip(np.asarray(proba), EPS, None)) / T
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def fit_temperature(proba: np.ndarray, y: np.ndarray) -> float:
    """val에서 negative log-likelihood를 최소화하는 T를 찾는다."""
    y = np.asarray(y)
    rows = np.arange(len(y))

    def nll(T: float) -> float:
        scaled = apply_temperature(proba, T)
        return float(-np.log(np.clip(scaled[rows, y], EPS, None)).mean())

    return float(minimize_scalar(nll, bounds=(0.05, 10.0), method="bounded").x)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `./venv/bin/pytest tests/test_calibration.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 실제 캘리브레이션 실행**

`scripts/calibrate_model.py`로 val에서 T를 적합하고 test에서 ECE 개선을 확인한다. 신뢰도 다이어그램을 `output/metrics/reliability_2025.png`로 저장하고, `models/calibration.json`에 `{method, temperature, ece_before, ece_after}`를 쓴다.

Expected: `ece_after < ece_before`. 개선이 없으면 캘리브레이션을 적용하지 않고 `temperature: 1.0`으로 기록한다.

- [ ] **Step 6: 커밋**

```bash
git add models/calibration.py tests/test_calibration.py scripts/calibrate_model.py \
        models/calibration.json output/metrics/reliability_2025.png
git commit -m "feat: 온도 스케일링 기반 확률 캘리브레이션

화면에 확률을 그대로 표시하므로 확신도가 실제 빈도와 맞아야 한다.
온도 스케일링은 순위를 바꾸지 않아 top-k 정확도는 유지된다."
```

---

### Task 10: 서빙 통합

**Files:**
- Modify: `services/prediction_service.py`
- Modify: `tests/test_prediction_service.py`
- Modify: 호출부 — `app.py`, `services/scouting_service.py` (`build_feature_row` 시그니처 변경 반영)

**Interfaces:**
- Consumes: Task 6·8·9의 아티팩트
- Produces:
  - `PredictionService(root_dir=ROOT_DIR, backend: str = "lgbm")`
  - `build_feature_row(context, recent_pitches, priors: dict | None = None) -> dict`
  - `predict_top_k(context, recent_pitches, k=3) -> list[tuple[str, float]]` — **반환 형식 불변**
  - `predict_full_proba(context, recent_pitches) -> dict[str, float]` — **반환 형식 불변**

**주의**: `predict_top_k`·`predict_full_proba`의 **반환 형식은 절대 바꾸지 않는다.** UI와 `services/scouting_service.py`가 그대로 동작해야 한다.

- [ ] **Step 1: 회귀 기준선 확인**

Run: `./venv/bin/pytest tests/test_prediction_service.py -v`
Expected: PASS. 여기서 실패하면 이전 태스크에서 뭔가 깨진 것이므로 먼저 고친다.

- [ ] **Step 2: 새 백엔드 테스트 추가**

`tests/test_prediction_service.py`에 추가한다. 기존 파일의 context/recent_pitches 픽스처 이름을 확인해 재사용한다.

```python
def test_lgbm_backend_returns_same_shape_as_before():
    from services.prediction_service import PredictionService

    service = PredictionService(backend="lgbm")
    top3 = service.predict_top_k(_sample_context(), _sample_recent_pitches(), k=3)

    assert len(top3) == 3
    assert all(isinstance(label, str) and isinstance(p, float) for label, p in top3)
    assert top3 == sorted(top3, key=lambda t: -t[1])


def test_full_proba_sums_to_one():
    from services.prediction_service import PredictionService

    service = PredictionService(backend="lgbm")
    proba = service.predict_full_proba(_sample_context(), _sample_recent_pitches())

    assert abs(sum(proba.values()) - 1.0) < 1e-6


def test_unknown_pitcher_does_not_raise():
    """prior를 못 찾는 투수도 예측이 실패하면 안 된다."""
    from services.prediction_service import PredictionService

    service = PredictionService(backend="lgbm")
    context = {**_sample_context(), "pitcher": 999999, "batter": 999999}

    assert len(service.predict_top_k(context, _sample_recent_pitches(), k=3)) == 3
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `./venv/bin/pytest tests/test_prediction_service.py -v -k "lgbm or full_proba or unknown"`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'backend'`

- [ ] **Step 4: `PredictionService` 확장**

다음을 구현한다.

- `backend` 파라미터(`"lgbm"` 기본 / `"rf"`)로 모델 로드 분기
- LightGBM booster + `next_pitch_lgbm_features.json`의 `feature_cols` 로드
- 기동 시 1회 prior 테이블 로드 — `pitcher_pitch_profile`·`count_pitch_profile`에서 만든 prior를 dict로 캐싱
- `build_feature_row`에 `priors` 인자를 받아 prior/시간 피처 컬럼을 채움
- prior를 못 찾으면 리그 평균으로 채움 — **예측이 예외로 죽지 않게 한다**
- `models/calibration.json`이 있으면 `apply_temperature` 적용
- `models/ensemble_config.json`의 `adopted`가 true면 `SeqPredictor`를 로드해 `blend`

- [ ] **Step 5: 전체 테스트 통과 확인**

Run: `./venv/bin/pytest tests/ -v`
Expected: 전체 PASS

- [ ] **Step 6: 앱 기동 확인**

Run: `./venv/bin/python app.py`
`http://localhost:7862` 접속 → 투수 모드 분석 1회 실행 → Top-3 표시 확인 → 프로세스 종료

- [ ] **Step 7: 추론 시간 측정**

`PredictionService.predict_top_k`를 동일 입력으로 20회 반복해 평균/최소/최대를 측정한다. 기존 기준선은 23.6ms. 결과를 `output/metrics/inference_latency.json`에 저장한다.

- [ ] **Step 8: 커밋**

```bash
git add services/prediction_service.py tests/test_prediction_service.py \
        app.py services/scouting_service.py output/metrics/inference_latency.json
git commit -m "feat: 서빙 경로를 LightGBM(+캘리브레이션/앙상블)으로 전환

predict_top_k / predict_full_proba의 반환 형식은 유지해 UI 회귀를 막는다.
prior를 못 찾는 투수/타자는 리그 평균으로 채워 예측이 실패하지 않게 한다."
```

---

### Task 11: 배포 아티팩트 결정 + Render 검증

**Files:**
- Modify: `requirements-deploy.txt`
- Modify: `.github/workflows/keep-warm.yml` 인근 배포 설정 (존재하는 파일 확인 후)
- Delete (조건부): `scripts/train_deploy_model.py`, `models/next_pitch_model_deploy.joblib`

- [ ] **Step 1: 모델 크기 실측**

Run: `ls -la models/next_pitch_lgbm.txt models/seq_model_weights.npz`

- [ ] **Step 2: 티어 통합 판정**

- **LightGBM 모델 < 50MB**: full/deploy 티어를 **통합한다.** `scripts/train_deploy_model.py`와 `models/next_pitch_model_deploy.joblib`을 제거하고, `services/prediction_service.py`의 `PITCH_MODEL_FILE` 환경변수 분기도 정리한다
- **≥ 50MB**: 축소 파라미터(`num_leaves` 축소, `num_boost_round` 제한)로 deploy 전용 아티팩트를 따로 만든다

- [ ] **Step 3: 배포 의존성 정리**

`requirements-deploy.txt`에 `lightgbm`이 있는지 확인한다. `scikit-learn`은 `top_k_accuracy_score`가 서빙 경로에 쓰이지 않으면 제거 가능하나, `scipy`(캘리브레이션 `minimize_scalar`는 학습 시점에만 필요)와 함께 실제 import 그래프를 확인한 뒤 결정한다. **TensorFlow·torch는 절대 추가하지 않는다.**

- [ ] **Step 4: 로컬 메모리 검증**

Run:
```bash
./venv/bin/python -c "
import resource, time
t = time.perf_counter()
from services.prediction_service import PredictionService
s = PredictionService()
print(f'로드 {time.perf_counter()-t:.2f}s')
print('최대 메모리 MB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024*1024))
"
```
Expected: 최대 메모리 400MB 미만. 넘으면 deploy 티어를 분리한다.

- [ ] **Step 5: 배포 후 실제 확인**

푸시 후 `https://diamondscout-ai.onrender.com`에서 분석 1회 실행. Render 로그에 OOM(`Ran out of memory`)이 없는지 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add requirements-deploy.txt
git commit -m "chore: LightGBM 전환에 맞춰 배포 아티팩트 정리"
```

---

### Task 12: 문서 갱신 + ADR-0003

**Files:**
- Modify: `docs/PERFORMANCE.md`
- Modify: `docs/ADR.md`
- Modify: `README.md`

- [ ] **Step 1: `docs/PERFORMANCE.md` 재작성**

모든 모델을 **동일 test split · 동일 표본 수**로 재평가한 표로 교체한다. 현재 문서는 RF(88,983건)와 LSTM(10,000건)을 서로 다른 표본으로 비교하고 있어 엄밀하지 않다고 스스로 각주를 달아둔 상태다.

| 모델 | top-1 | top-3 | 크기 | 추론 |
|---|---|---|---|---|
| 최빈값 베이스라인 (FF) | 31.5% | 60.7% | — | — |
| RF (기존 56피처) | 39.5% | 78.7% | 188MB | 23.6ms |
| RF (+보강 피처) | Task 5 | Task 5 | 측정 | 측정 |
| LightGBM (+보강 피처) | Task 6 | Task 6 | 측정 | 측정 |
| + GRU 앙상블 | Task 8 (미채택 시 명시) | | | |

캘리브레이션 ECE(before/after)와 신뢰도 다이어그램 경로도 기재한다.

- [ ] **Step 2: ADR-0003 작성 + ADR-0001 superseded 표시**

`docs/ADR.md`에 ADR-0003(다음 구종 예측 — 피처 보강 + LightGBM 전환)을 추가하고, ADR-0001 제목 아래에 `> **상태: Superseded by ADR-0003 (2026-08-16)**`를 넣는다.

ADR-0003에 반드시 담을 것:
- 기존 모델에 투수 정체성 신호가 없었다는 진단
- 피처 기여분(Task 5)과 모델 교체 기여분(Task 6)을 분리 측정한 결과
- LightGBM 선택 이유(정확도 + 크기 → Render 제약 해소)
- **채택하지 않은 것과 그 이유** — 앙상블 미채택 시 근거, TensorFlow 서빙을 포기하고 numpy 내보내기를 택한 이유

- [ ] **Step 3: README 성능 수치 갱신**

README에 모델 정확도·모델명(RandomForest)이 언급된 부분을 새 수치·모델로 고친다. 헤더 설명문의 "다음 구종 예측(RandomForest)" 문구도 포함한다.

- [ ] **Step 4: 전체 테스트 실행**

Run: `./venv/bin/pytest tests/ -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add docs/PERFORMANCE.md docs/ADR.md README.md
git commit -m "docs: 정확도 고도화 결과 기록 + ADR-0003

모든 모델을 동일 test split으로 재평가한 표로 교체한다.
ADR-0001(RF 프로덕션 유지)은 ADR-0003으로 대체됨을 표시한다."
```

---

## 자체 검토 결과

**스펙 커버리지**

| 스펙 항목 | 태스크 |
|---|---|
| A-1 (a) 투수 아스널 prior | Task 2 |
| A-1 (b) 카운트 조건부 prior | Task 2 |
| A-1 (c) 타자 매치업 | Task 2 (`build_batter_matchup_features`) + Task 4 (조인·폴백) |
| A-1 (d) 시간·피로 피처 | Task 3 |
| A-1 (e) 누수 방지 | Task 2·4, `tests/test_no_leakage.py` |
| A-2 LightGBM 전환 | Task 6 |
| A-3 시퀀스 앙상블 | Task 7·8 |
| A-4 캘리브레이션 | Task 9 |
| A-5 2-티어 아티팩트 | Task 11 |
| A-6 성능 문서 갱신 | Task 12 |
| B-4 타자 이름 (데이터 측) | Task 1 |

누락 없음.

**타입 일관성 확인**

- `pitcher_prior_{i}` / `count_prior_{i}` 컬럼명이 Task 2 정의 → Task 4 `attach_priors` → Task 5 `NEW_PREFIXES`에서 일치
- `batter_whiff_avg` 등 4개 컬럼명이 Task 2 정의 → Task 4 `BATTER_FEATURE_COLS` → Task 5 `NEW_PREFIXES`(`"batter_"`)에서 일치
- `predict_proba(booster, X)`가 Task 6 정의와 Task 8·10 사용처에서 일치
- `SeqPredictor.predict_proba(seq)`가 Task 7 정의와 Task 8·10 사용처에서 일치
- `TARGET_COL`은 `models/next_pitch_model.py`의 기존 상수를 재사용하며 재정의하지 않음
- `SEQ_LEN = 5`가 Task 7 모듈 상수와 테스트(`SEQ_LEN, N_FEAT, N_CLASS = 5, 6, 11`)에서 일치

**남은 가정**

- LightGBM 4.7.0이 numpy 2.5.0 / pandas 3.0.3과 호환된다고 가정한다. Task 6 Step 1에서 import가 실패하면 호환 버전을 찾아 고정하고 이 계획서에 기록한다.
- `scipy==1.18.0`이 이미 `requirements.txt`에 있어 `minimize_scalar` 사용에 문제가 없다(확인됨).
- Task 4 Step 6의 전처리 재실행은 59만 행 규모라 수 분이 걸린다. 소요 시간을 측정해 기록한다.
