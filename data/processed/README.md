# data/processed 전처리 산출물

`data/preprocess_statcast.py`가 `data/raw/statcast_{year}_full.csv`를 읽어 생성한다. raw 데이터는 읽기 전용으로만 사용된다.

실행:

```bash
./venv/bin/python data/preprocess_statcast.py --year 2025
```

## 공통 전처리 규칙

- `pitch_type`이 없는 행 제거
- `game_pk`, `at_bat_number`, `pitch_number` 기준 정렬
- `stand`, `p_throws`: L=0, R=1 (`stand_enc`, `p_throws_enc`)
- `inning_topbot`: Top=1, Bot=0 (`inning_topbot_enc`)
- `on_1b`, `on_2b`, `on_3b`: 결측(주자 없음)=0, 값 있음(주자 있음)=1
- `score_diff` = `bat_score` - `fld_score`
- `pitch_result_group`: `description` 기준 `whiff` / `called_strike` / `foul` / `ball` / `hit_by_pitch` / `in_play` / `other` 로 분류
- `pitch_label`: 전체 투구 수 1,000개 미만인 희귀 구종은 `OTHER`로 통합, `pitch_label_id`는 `pitch_label_mapping.json` 기준
- `zone_cell`: 스트라이크존 밖=0, 존 안=1~9 (`plate_x`를 좌우 존 폭(±0.83ft) 기준 3등분, `plate_z`를 타자별 `sz_bot`~`sz_top` 기준 3등분한 3x3 격자, row 0=존 하단·col 0=좌측 기준 `row*3+col+1`). 존 밖은 clamp하지 않음
- `zone_cell_clamped`: UI 히트맵 등 표시용으로, 존 밖 좌표도 가장 가까운 1~9 셀에 투영한 값 (모델 feature/target으로는 사용하지 않음)
- 결과 플래그: `is_whiff`, `is_ball`, `is_foul`, `is_in_play`(type=='X'), `is_hit`, `is_extra_base_hit`, `is_home_run`, `is_walk`, `is_strikeout`, `hard_hit`(launch_speed>=95mph), `risky_contact`(인플레이 + 강한 타구 또는 라인드라이브/뜬공)

## 파일별 설명

### next_pitch_dataset_{year}.csv
같은 경기(`game_pk`) + 같은 투수(`pitcher`) 내에서 직전 5구 + 현재 상황 정보를 feature로, 현재 구종을 target으로 사용하는 다음 구종 예측용 데이터셋. 직전 5구가 부족한 초반 투구는 제외.

- 식별 컬럼: `game_date`, `game_pk`, `pitcher`, `batter`, `at_bat_number`, `pitch_number`
- 현재 상황 feature (투구 전에 이미 알 수 있는 값만 사용, 결과성 피처인 release_speed/plate_x/plate_z 등은 현재 투구 기준으로는 포함하지 않음): `balls`, `strikes`, `outs_when_up`, `inning`, `inning_topbot_enc`, `on_1b`, `on_2b`, `on_3b`, `score_diff`, `stand_enc`, `p_throws_enc`
- 과거 5구 feature: `{pitch_label_id, release_speed, pfx_x, pfx_z, plate_x, plate_z, zone_cell, balls, strikes}_lag{1~5}` (lag1=바로 이전 구, 과거 투구의 결과값이므로 사용 가능)
- target: `target_pitch_label_id`

### pitcher_pitch_profile_{year}.csv
투수별 구종 비율. `pitcher`, `player_name`, `pitch_label`, `pitch_count`, `pitcher_total_pitches`, `pitch_ratio`

### count_pitch_profile_{year}.csv
투수+카운트별 구종 비율. `pitcher`, `balls`, `strikes`, `pitch_label`, `pitch_count`, `count_total_pitches`, `pitch_ratio`

### zone_risk_profile_{year}.csv
투수+구종+zone_cell별 위험 지표. `pitcher`, `pitch_label`, `zone_cell`, `pitch_count`, `whiff_rate`, `ball_rate`, `in_play_rate`, `extra_base_hit_rate`, `home_run_rate`, `hard_hit_rate`, `risky_contact_rate`, `avg_delta_run_exp`

### batter_matchup_profile_{year}.csv
타자+타자좌우+투수좌우+구종별 반응 지표. `batter`, `stand`, `p_throws`, `pitch_label`, `pitch_count`, `whiff_rate`, `foul_rate`, `in_play_rate`, `hard_hit_rate`, `extra_base_hit_rate`, `avg_delta_run_exp`

### pitch_label_mapping.json
`label_to_id`, `id_to_label`, `rare_pitch_min_count`(희귀 구종 기준값, 1,000)
