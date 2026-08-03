"""
DiamondScout AI - 다음 구종 예측 모델
data/processed/next_pitch_dataset_{year}.csv를 학습해 다음 투구 구종(top-3)을 예측한다.

현재는 RandomForest baseline이며, fit/predict_proba 인터페이스를 지키는 다른 모델
(LSTM/MLP 등 딥러닝 모델 포함)로 build_model()만 교체하면 확장할 수 있도록 구성했다.
"""

import argparse
import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, top_k_accuracy_score

ID_COLS = ["game_date", "game_pk", "pitcher", "batter", "at_bat_number", "pitch_number"]
TARGET_COL = "target_pitch_label_id"
RANDOM_STATE = 42


def load_dataset(root: str, year: int) -> pd.DataFrame:
    path = os.path.join(root, "data", "processed", f"next_pitch_dataset_{year}.csv")
    return pd.read_csv(path)


def load_label_mapping(root: str) -> dict[int, str]:
    path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    return {int(k): v for k, v in mapping["id_to_label"].items()}


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ID_COLS + [TARGET_COL]]


def time_based_split(df: pd.DataFrame, train_ratio: float = 0.7, val_ratio: float = 0.15):
    """game_pk를 경기 시작일 기준으로 정렬한 뒤 통째로 train/val/test에 배정한다.
    같은 경기의 투구가 서로 다른 split에 섞이지 않도록 해 데이터 누수를 줄인다."""
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


def build_model() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=150,
        max_depth=16,
        min_samples_leaf=30,
        n_jobs=-1,
        random_state=RANDOM_STATE,
    )


def evaluate(model, X: pd.DataFrame, y: pd.Series, id_to_label: dict[int, str]) -> dict:
    classes = model.classes_
    y_pred = model.predict(X)
    y_proba = model.predict_proba(X)

    top1 = top_k_accuracy_score(y, y_proba, k=1, labels=classes)
    top3 = top_k_accuracy_score(y, y_proba, k=3, labels=classes)

    target_names = [id_to_label[c] for c in classes]
    report = classification_report(y, y_pred, labels=classes, target_names=target_names, zero_division=0)
    cm = confusion_matrix(y, y_pred, labels=classes)
    cm_df = pd.DataFrame(cm, index=target_names, columns=target_names)

    return {
        "top1_accuracy": float(top1),
        "top3_accuracy": float(top3),
        "classification_report": report,
        "confusion_matrix": cm_df,
        "n_samples": int(len(y)),
    }


def predict_top_k(model, feature_row, feature_cols: list[str], id_to_label: dict[int, str], k: int = 3):
    """feature_row: dict, pandas Series, 또는 단일 행 DataFrame. Top-k (구종, 확률) 리스트를 반환한다."""
    if isinstance(feature_row, dict):
        x = pd.DataFrame([feature_row])[feature_cols]
    elif isinstance(feature_row, pd.Series):
        x = feature_row[feature_cols].to_frame().T
    else:
        x = feature_row[feature_cols]

    proba = model.predict_proba(x)[0]
    classes = model.classes_
    top_idx = np.argsort(proba)[::-1][:k]
    return [(id_to_label[classes[i]], float(proba[i])) for i in top_idx]


def save_outputs(root: str, year: int, model, feature_cols: list[str], val_metrics: dict, test_metrics: dict) -> None:
    models_dir = os.path.join(root, "models")
    model_path = os.path.join(models_dir, "next_pitch_model.joblib")
    joblib.dump({"model": model, "feature_cols": feature_cols, "year": year}, model_path)
    print(f"[저장] {model_path}")

    out_dir = os.path.join(root, "data", "processed", "model_outputs")
    os.makedirs(out_dir, exist_ok=True)

    metrics = {
        "year": year,
        "n_features": len(feature_cols),
        "feature_cols": feature_cols,
        "validation": {
            "top1_accuracy": val_metrics["top1_accuracy"],
            "top3_accuracy": val_metrics["top3_accuracy"],
            "n_samples": val_metrics["n_samples"],
        },
        "test": {
            "top1_accuracy": test_metrics["top1_accuracy"],
            "top3_accuracy": test_metrics["top3_accuracy"],
            "n_samples": test_metrics["n_samples"],
        },
    }
    metrics_path = os.path.join(out_dir, f"metrics_{year}.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[저장] {metrics_path}")

    report_path = os.path.join(out_dir, f"classification_report_test_{year}.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(test_metrics["classification_report"])
    print(f"[저장] {report_path}")

    cm_path = os.path.join(out_dir, f"confusion_matrix_test_{year}.csv")
    test_metrics["confusion_matrix"].to_csv(cm_path)
    print(f"[저장] {cm_path}")


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()

    df = load_dataset(root, args.year)
    id_to_label = load_label_mapping(root)
    feature_cols = get_feature_columns(df)

    train_df, val_df, test_df = time_based_split(df)
    print(f"[분할] train={len(train_df):,} val={len(val_df):,} test={len(test_df):,} (game_pk 시간순)")

    X_train, y_train = train_df[feature_cols], train_df[TARGET_COL]
    X_val, y_val = val_df[feature_cols], val_df[TARGET_COL]
    X_test, y_test = test_df[feature_cols], test_df[TARGET_COL]

    model = build_model()
    model.fit(X_train, y_train)
    print("[학습 완료]")

    val_metrics = evaluate(model, X_val, y_val, id_to_label)
    test_metrics = evaluate(model, X_test, y_test, id_to_label)
    print(f"[검증] top1={val_metrics['top1_accuracy']:.4f} top3={val_metrics['top3_accuracy']:.4f}")
    print(f"[테스트] top1={test_metrics['top1_accuracy']:.4f} top3={test_metrics['top3_accuracy']:.4f}")

    save_outputs(root, args.year, model, feature_cols, val_metrics, test_metrics)
    print("\n[전체 완료]")


if __name__ == "__main__":
    main()
