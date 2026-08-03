"""
DiamondScout AI - 딥러닝 학습용 배열 준비 (pandas 전용, TensorFlow는 import하지 않음)

이 환경에서는 pandas로 CSV를 로드/가공한 뒤 같은 프로세스에서 TensorFlow model.fit()을
호출하면 무한 대기(hang)하는 문제가 있어(sklearn 유무와 무관하게 재현됨), 데이터 준비
단계를 별도 프로세스로 완전히 분리했다. deep_next_pitch_model.py가 subprocess로 이
스크립트를 먼저 실행해 배열을 .npz로 저장하고, 이후 순수 numpy+TF 프로세스에서 그
파일만 읽어 학습한다.
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

ID_COLS = ["game_date", "game_pk", "pitcher", "batter", "at_bat_number", "pitch_number"]
TARGET_COL = "target_pitch_label_id"

LOOKBACK = 5
LAG_ORDER = [5, 4, 3, 2, 1]  # 시퀀스 순서: 과거 -> 최근
CONTINUOUS_LAG_COLS = ["release_speed", "pfx_x", "pfx_z", "plate_x", "plate_z", "zone_cell", "balls", "strikes"]
CURRENT_CONTEXT_COLS = [
    "balls", "strikes", "outs_when_up", "inning", "inning_topbot_enc",
    "on_1b", "on_2b", "on_3b", "score_diff", "stand_enc", "p_throws_enc",
]


def load_dataset(root: str, year: int) -> pd.DataFrame:
    path = os.path.join(root, "data", "processed", f"next_pitch_dataset_{year}.csv")
    return pd.read_csv(path)


def load_label_mapping(root: str) -> dict[int, str]:
    path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    return {int(k): v for k, v in mapping["id_to_label"].items()}


def time_based_split(df: pd.DataFrame, train_ratio: float = 0.7, val_ratio: float = 0.15):
    game_order = df.groupby("game_pk")["game_date"].min().sort_values().index.tolist()
    n = len(game_order)
    train_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))

    train_games = set(game_order[:train_end])
    val_games = set(game_order[train_end:val_end])
    test_games = set(game_order[val_end:])

    train_df = df[df["game_pk"].isin(train_games)].reset_index(drop=True)
    val_df = df[df["game_pk"].isin(val_games)].reset_index(drop=True)
    test_df = df[df["game_pk"].isin(test_games)].reset_index(drop=True)
    return train_df, val_df, test_df


def sample_split(df: pd.DataFrame, max_rows: int, seed: int = 42) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df
    return df.sample(n=max_rows, random_state=seed).sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)


def fit_scaler(x: np.ndarray) -> dict[str, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    return {"mean": mean.astype("float64"), "std": std.astype("float64")}


def apply_scaler(x: np.ndarray, scaler: dict[str, np.ndarray]) -> np.ndarray:
    return (x - scaler["mean"]) / scaler["std"]


def build_sequence_input(df: pd.DataFrame, n_classes: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(df)
    pitch_ids = np.zeros((n, LOOKBACK), dtype="int64")
    cont = np.zeros((n, LOOKBACK, len(CONTINUOUS_LAG_COLS)), dtype="float32")
    for t, lag in enumerate(LAG_ORDER):
        pitch_ids[:, t] = df[f"pitch_label_id_lag{lag}"].to_numpy()
        for j, col in enumerate(CONTINUOUS_LAG_COLS):
            cont[:, t, j] = df[f"{col}_lag{lag}"].to_numpy()
    onehot = np.eye(n_classes, dtype="float32")[pitch_ids]
    return onehot, cont


def build_inputs(df: pd.DataFrame, n_classes: int, seq_scaler: dict, context_scaler: dict) -> tuple[np.ndarray, np.ndarray]:
    onehot, cont = build_sequence_input(df, n_classes)
    n, t, f = cont.shape
    cont_scaled = apply_scaler(cont.reshape(-1, f), seq_scaler).reshape(n, t, f)
    seq = np.concatenate([onehot, cont_scaled], axis=-1)

    context_raw = df[CURRENT_CONTEXT_COLS].to_numpy(dtype="float64")
    context = apply_scaler(context_raw, context_scaler)

    return np.ascontiguousarray(seq, dtype="float32"), np.ascontiguousarray(context, dtype="float32")


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--max-train", type=int, default=50000)
    parser.add_argument("--max-val", type=int, default=10000)
    parser.add_argument("--max-test", type=int, default=10000)
    parser.add_argument("--out", type=str, required=True)
    args = parser.parse_args()

    df = load_dataset(root, args.year)
    id_to_label = load_label_mapping(root)
    n_classes = len(id_to_label)

    train_df, val_df, test_df = time_based_split(df)
    print(f"[분할] train={len(train_df):,} val={len(val_df):,} test={len(test_df):,} (game_pk 시간순)", flush=True)

    train_df = sample_split(train_df, args.max_train)
    val_df = sample_split(val_df, args.max_val)
    test_df = sample_split(test_df, args.max_test)
    print(f"[샘플링] train={len(train_df):,} val={len(val_df):,} test={len(test_df):,}", flush=True)

    _, cont_train = build_sequence_input(train_df, n_classes)
    n, t, f = cont_train.shape
    seq_scaler = fit_scaler(cont_train.reshape(-1, f))
    context_scaler = fit_scaler(train_df[CURRENT_CONTEXT_COLS].to_numpy(dtype="float64"))

    seq_train, ctx_train = build_inputs(train_df, n_classes, seq_scaler, context_scaler)
    seq_val, ctx_val = build_inputs(val_df, n_classes, seq_scaler, context_scaler)
    seq_test, ctx_test = build_inputs(test_df, n_classes, seq_scaler, context_scaler)

    y_train = train_df[TARGET_COL].to_numpy()
    y_val = val_df[TARGET_COL].to_numpy()
    y_test = test_df[TARGET_COL].to_numpy()

    np.savez(
        args.out,
        seq_train=seq_train, ctx_train=ctx_train, y_train=y_train,
        seq_val=seq_val, ctx_val=ctx_val, y_val=y_val,
        seq_test=seq_test, ctx_test=ctx_test, y_test=y_test,
        seq_mean=seq_scaler["mean"], seq_std=seq_scaler["std"],
        context_mean=context_scaler["mean"], context_std=context_scaler["std"],
    )
    print(f"[저장] {args.out}", flush=True)
    print("[준비 완료]", flush=True)


if __name__ == "__main__":
    main()
