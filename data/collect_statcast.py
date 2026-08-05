"""
MLB Statcast 데이터 수집 (DiamondScout AI)
PRD 8번 항목의 전체 컬럼을 포함해 시즌별로 월 단위 청크 수집 후 캐싱한다.
"""

import argparse
import os
import signal
import time

import pandas as pd
import pybaseball
import requests

pybaseball.cache.enable()

REQUEST_TIMEOUT_SEC = 180


class RequestHangError(Exception):
    pass


def _alarm_handler(signum, frame):
    raise RequestHangError(f"statcast 요청이 {REQUEST_TIMEOUT_SEC}초 내에 응답 없음")

COLUMNS = [
    # 매치업
    "game_date", "game_pk", "at_bat_number", "pitch_number",
    "pitcher", "batter", "player_name", "stand", "p_throws",
    "home_team", "away_team", "inning_topbot",
    # 투구 기본
    "pitch_type", "pitch_name", "release_speed", "release_spin_rate",
    # 궤적
    "release_pos_x", "release_pos_y", "release_pos_z",
    "vx0", "vy0", "vz0", "ax", "ay", "az",
    # 움직임/위치
    "pfx_x", "pfx_z", "plate_x", "plate_z", "zone", "sz_top", "sz_bot",
    # 경기 상황
    "balls", "strikes", "outs_when_up", "inning",
    "on_1b", "on_2b", "on_3b", "bat_score", "fld_score",
    # 투구 결과
    "description", "type",
    # 타석 결과
    "events",
    # 타구 품질
    "launch_speed", "launch_angle", "hit_distance_sc", "bb_type",
    # 기대 지표
    "estimated_woba_using_speedangle", "woba_value", "delta_run_exp",
]


def season_months(year: int) -> list[tuple[str, str]]:
    return [
        (f"{year}-04-01", f"{year}-04-30"),
        (f"{year}-05-01", f"{year}-05-31"),
        (f"{year}-06-01", f"{year}-06-30"),
        (f"{year}-07-01", f"{year}-07-31"),
        (f"{year}-08-01", f"{year}-08-31"),
        (f"{year}-09-01", f"{year}-09-30"),
        (f"{year}-10-01", f"{year}-10-05"),
    ]


def collect_month(start_date: str, end_date: str, save_path: str) -> pd.DataFrame:
    if os.path.exists(save_path):
        print(f"[캐시] {save_path}")
        return pd.read_csv(save_path)

    print(f"[수집] {start_date} ~ {end_date}")
    for attempt in range(1, 4):
        try:
            signal.signal(signal.SIGALRM, _alarm_handler)
            signal.alarm(REQUEST_TIMEOUT_SEC)
            df = pybaseball.statcast(start_dt=start_date, end_dt=end_date)
            signal.alarm(0)
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, RequestHangError) as e:
            signal.alarm(0)
            wait = 10 * attempt
            print(f"[재시도 {attempt}/3] {e} → {wait}초 대기")
            time.sleep(wait)
    else:
        raise RuntimeError(f"{start_date}~{end_date} 수집 3회 실패")

    available = [c for c in COLUMNS if c in df.columns]
    df = df[available].copy()
    df = df.dropna(subset=["pitch_type"])
    df = df[df["pitch_type"] != ""]

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    df.to_csv(save_path, index=False)
    print(f"[저장] {save_path} ({len(df):,}개 투구)")
    return df


def collect_season(year: int, root: str) -> pd.DataFrame:
    dfs = []
    for start, end in season_months(year):
        path = os.path.join(root, "data", "raw", f"statcast_{start[:7]}.csv")
        dfs.append(collect_month(start, end, path))

    full_df = pd.concat(dfs, ignore_index=True)
    out = os.path.join(root, "data", "raw", f"statcast_{year}_full.csv")
    full_df.to_csv(out, index=False)
    print(f"[시즌 완료] {year}: {len(full_df):,}개 투구 → {out}")
    return full_df


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="+", default=[2021, 2022, 2023, 2024, 2025])
    args = parser.parse_args()

    for year in args.years:
        collect_season(year, root)

    print("\n[전체 완료]")
