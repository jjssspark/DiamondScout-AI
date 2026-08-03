"""
DiamondScout AI - 다음 구종 예측 딥러닝 모델 (LSTM + Dense, MLP 대체 가능)
data/processed/next_pitch_dataset_{year}.csv를 학습해 다음 투구 구종(top-3)을 예측한다.
RandomForest baseline(next_pitch_model.py)과 동일한 시간순 분할 로직을 사용해 성능을 비교한다.

입력 구조:
- 과거 5구 시퀀스(구종 원-핫 + 연속값)는 LSTM(또는 MLP에서는 Flatten) 입력으로 사용
- 현재 상황 feature는 별도 Dense 입력으로 사용
- 두 출력을 concat해 11개 구종 softmax로 분류

주의: 이 환경에서는 pandas로 CSV를 로드/가공한 뒤 같은 프로세스에서 TensorFlow
model.fit()을 호출하면 첫 배치에서 무한 대기(hang)하는 문제가 실측으로 확인됐다
(sklearn 제거, contiguous 배열 강제, 싱글스레드, eager 모드 모두 무관하게 재현됨;
동일 배열을 pandas 없는 새 프로세스에서 로드하면 정상 동작). 그래서 데이터 준비
(pandas)는 _prepare_deep_pitch_data.py를 별도 subprocess로 실행해 처리하고, 이
스크립트는 그 결과 .npz만 numpy로 읽어 TensorFlow 학습을 전담한다.

또한 전체 59만 행으로 LSTM을 학습하면(sklearn 제거 후에도) 계속 멈춰서, 학습 규모를
샘플링(--max-train 등)으로 줄였다. 그래도 LSTM이 멈추면 --model-type mlp로 대체한다.
"""

import argparse
import json
import os
import subprocess
import sys

import numpy as np
from tensorflow import keras

TARGET_COL = "target_pitch_label_id"
LOOKBACK = 5


def prepare_arrays(root: str, year: int, max_train: int, max_val: int, max_test: int) -> str:
    out_dir = os.path.join(root, "data", "processed", "model_outputs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"deep_arrays_{year}.npz")

    prep_script = os.path.join(root, "models", "_prepare_deep_pitch_data.py")
    cmd = [
        sys.executable, prep_script,
        "--year", str(year),
        "--max-train", str(max_train),
        "--max-val", str(max_val),
        "--max-test", str(max_test),
        "--out", out_path,
    ]
    print(f"[준비] pandas 데이터 준비를 별도 프로세스로 실행: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    return out_path


def load_label_mapping(root: str) -> dict[int, str]:
    path = os.path.join(root, "data", "processed", "pitch_label_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    return {int(k): v for k, v in mapping["id_to_label"].items()}


def build_model(seq_feature_dim: int, context_dim: int, n_classes: int, model_type: str = "lstm") -> keras.Model:
    seq_input = keras.Input(shape=(LOOKBACK, seq_feature_dim), name="pitch_sequence")
    context_input = keras.Input(shape=(context_dim,), name="current_context")

    if model_type == "mlp":
        # 이 환경에서 LSTM 학습이 멈추는 경우의 대체 경로: 시퀀스를 펼쳐(Flatten) Dense로만 처리한다.
        seq_flat = keras.layers.Flatten()(seq_input)
        merged = keras.layers.Concatenate()([seq_flat, context_input])
        merged = keras.layers.Dense(128, activation="relu")(merged)
        merged = keras.layers.Dropout(0.3)(merged)
        merged = keras.layers.Dense(64, activation="relu")(merged)
    else:
        lstm_out = keras.layers.LSTM(64)(seq_input)
        dense_out = keras.layers.Dense(32, activation="relu")(context_input)
        merged = keras.layers.Concatenate()([lstm_out, dense_out])
        merged = keras.layers.Dense(64, activation="relu")(merged)
        merged = keras.layers.Dropout(0.3)(merged)

    output = keras.layers.Dense(n_classes, activation="softmax")(merged)

    model = keras.Model(inputs=[seq_input, context_input], outputs=output)
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    return model


# ---- numpy 전용 평가 지표 (sklearn.metrics 대체) ----

def top_k_accuracy_np(y_true: np.ndarray, y_proba: np.ndarray, k: int) -> float:
    top_k = np.argpartition(-y_proba, kth=k - 1, axis=1)[:, :k]
    return float(np.mean((top_k == y_true[:, None]).any(axis=1)))


def confusion_matrix_np(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> np.ndarray:
    cm = np.zeros((n_classes, n_classes), dtype="int64")
    np.add.at(cm, (y_true, y_pred), 1)
    return cm


def classification_report_np(y_true: np.ndarray, y_pred: np.ndarray, target_names: list[str]) -> str:
    n_classes = len(target_names)
    cm = confusion_matrix_np(y_true, y_pred, n_classes)

    precisions, recalls, f1s, supports = [], [], [], []
    lines = [f"{'':>12}{'precision':>10}{'recall':>10}{'f1-score':>10}{'support':>10}", ""]
    for i, name in enumerate(target_names):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum()) - tp
        fn = int(cm[i, :].sum()) - tp
        support = int(cm[i, :].sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
        supports.append(support)
        lines.append(f"{name:>12}{precision:>10.2f}{recall:>10.2f}{f1:>10.2f}{support:>10d}")

    total_support = int(cm.sum())
    accuracy = float(np.trace(cm)) / total_support if total_support > 0 else 0.0
    macro_p, macro_r, macro_f1 = float(np.mean(precisions)), float(np.mean(recalls)), float(np.mean(f1s))
    weighted_p = float(np.average(precisions, weights=supports))
    weighted_r = float(np.average(recalls, weights=supports))
    weighted_f1 = float(np.average(f1s, weights=supports))

    lines.append("")
    lines.append(f"{'accuracy':>12}{'':>10}{'':>10}{accuracy:>10.2f}{total_support:>10d}")
    lines.append(f"{'macro avg':>12}{macro_p:>10.2f}{macro_r:>10.2f}{macro_f1:>10.2f}{total_support:>10d}")
    lines.append(f"{'weighted avg':>12}{weighted_p:>10.2f}{weighted_r:>10.2f}{weighted_f1:>10.2f}{total_support:>10d}")
    return "\n".join(lines)


def confusion_matrix_to_csv(cm: np.ndarray, target_names: list[str], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("," + ",".join(target_names) + "\n")
        for name, row in zip(target_names, cm):
            f.write(name + "," + ",".join(str(int(v)) for v in row) + "\n")


def evaluate(model: keras.Model, seq: np.ndarray, context: np.ndarray, y: np.ndarray, id_to_label: dict[int, str]) -> dict:
    n_classes = len(id_to_label)
    y_proba = model.predict([seq, context], verbose=0)
    y_pred = np.argmax(y_proba, axis=1)

    top1 = top_k_accuracy_np(y, y_proba, k=1)
    top3 = top_k_accuracy_np(y, y_proba, k=3)

    target_names = [id_to_label[i] for i in range(n_classes)]
    report = classification_report_np(y, y_pred, target_names)
    cm = confusion_matrix_np(y, y_pred, n_classes)

    return {
        "top1_accuracy": top1,
        "top3_accuracy": top3,
        "classification_report": report,
        "confusion_matrix": cm,
        "target_names": target_names,
        "n_samples": int(len(y)),
    }


def save_outputs(root: str, year: int, model: keras.Model, val_metrics: dict, test_metrics: dict) -> dict:
    models_dir = os.path.join(root, "models")
    model_path = os.path.join(models_dir, "deep_next_pitch_model.keras")
    model.save(model_path)
    print(f"[저장] {model_path}")

    out_dir = os.path.join(root, "data", "processed", "model_outputs")
    os.makedirs(out_dir, exist_ok=True)

    rf_metrics_path = os.path.join(out_dir, f"metrics_{year}.json")
    comparison = None
    if os.path.exists(rf_metrics_path):
        with open(rf_metrics_path, "r", encoding="utf-8") as f:
            rf_metrics = json.load(f)
        comparison = {
            "random_forest": rf_metrics["test"],
            "deep_model": {
                "top1_accuracy": test_metrics["top1_accuracy"],
                "top3_accuracy": test_metrics["top3_accuracy"],
                "n_samples": test_metrics["n_samples"],
            },
            "better_top1": "deep_model" if test_metrics["top1_accuracy"] > rf_metrics["test"]["top1_accuracy"] else "random_forest",
            "better_top3": "deep_model" if test_metrics["top3_accuracy"] > rf_metrics["test"]["top3_accuracy"] else "random_forest",
        }

    metrics = {
        "year": year,
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
        "comparison_to_random_forest": comparison,
    }
    metrics_path = os.path.join(out_dir, f"deep_metrics_{year}.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[저장] {metrics_path}")

    report_path = os.path.join(out_dir, f"deep_classification_report_test_{year}.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(test_metrics["classification_report"])
    print(f"[저장] {report_path}")

    cm_path = os.path.join(out_dir, f"deep_confusion_matrix_test_{year}.csv")
    confusion_matrix_to_csv(test_metrics["confusion_matrix"], test_metrics["target_names"], cm_path)
    print(f"[저장] {cm_path}")

    return metrics


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--model-type", choices=["lstm", "mlp"], default="lstm")
    parser.add_argument("--max-train", type=int, default=50000)
    parser.add_argument("--max-val", type=int, default=10000)
    parser.add_argument("--max-test", type=int, default=10000)
    args = parser.parse_args()

    arrays_path = prepare_arrays(root, args.year, args.max_train, args.max_val, args.max_test)
    id_to_label = load_label_mapping(root)
    n_classes = len(id_to_label)

    data = np.load(arrays_path)
    seq_train, ctx_train, y_train = data["seq_train"], data["ctx_train"], data["y_train"]
    seq_val, ctx_val, y_val = data["seq_val"], data["ctx_val"], data["y_val"]
    seq_test, ctx_test, y_test = data["seq_test"], data["ctx_test"], data["y_test"]
    print(f"[로드] train={len(y_train):,} val={len(y_val):,} test={len(y_test):,} (model_type={args.model_type})")

    model = build_model(seq_feature_dim=seq_train.shape[-1], context_dim=ctx_train.shape[-1], n_classes=n_classes, model_type=args.model_type)
    model.summary()

    early_stop = keras.callbacks.EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)
    model.fit(
        [seq_train, ctx_train], y_train,
        validation_data=([seq_val, ctx_val], y_val),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=[early_stop],
        verbose=2,
    )
    print("[학습 완료]")

    val_metrics = evaluate(model, seq_val, ctx_val, y_val, id_to_label)
    test_metrics = evaluate(model, seq_test, ctx_test, y_test, id_to_label)
    print(f"[검증] top1={val_metrics['top1_accuracy']:.4f} top3={val_metrics['top3_accuracy']:.4f}")
    print(f"[테스트] top1={test_metrics['top1_accuracy']:.4f} top3={test_metrics['top3_accuracy']:.4f}")

    metrics = save_outputs(root, args.year, model, val_metrics, test_metrics)
    if metrics["comparison_to_random_forest"]:
        c = metrics["comparison_to_random_forest"]
        print(f"\n[비교] RandomForest top1={c['random_forest']['top1_accuracy']:.4f} vs "
              f"딥러닝 top1={c['deep_model']['top1_accuracy']:.4f} → top1 우세: {c['better_top1']}")
        print(f"[비교] RandomForest top3={c['random_forest']['top3_accuracy']:.4f} vs "
              f"딥러닝 top3={c['deep_model']['top3_accuracy']:.4f} → top3 우세: {c['better_top3']}")

    print("\n[전체 완료]")


if __name__ == "__main__":
    main()
