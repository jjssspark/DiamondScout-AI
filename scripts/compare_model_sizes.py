"""RandomForest 하이퍼파라미터별 (모델 크기 vs 정확도) 트레이드오프 측정.

무료 티어 호스팅(512MB RAM)에 올리려면 현재 188MB짜리 next_pitch_model.joblib을
크게 줄여야 한다. 트리 수·깊이·리프 최소 샘플을 바꿔가며 실제로 학습해 크기와
top-1/top-3 정확도를 함께 측정한다 - 어느 설정까지 줄여도 되는지 추측하지 않기 위함.

사용법:
    python scripts/compare_model_sizes.py
"""

import os
import sys
import tempfile
import time

import joblib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import top_k_accuracy_score

from models.next_pitch_model import (
    RANDOM_STATE,
    TARGET_COL,
    get_feature_columns,
    load_dataset,
    load_label_mapping,
    time_based_split,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (이름, n_estimators, max_depth, min_samples_leaf)
CANDIDATES = [
    ("현재값(baseline)", 150, 16, 30),
    ("중간 축소", 80, 14, 80),
    ("공격적 축소", 60, 12, 150),
    ("최대 축소", 40, 10, 300),
]


def model_size_mb(model, feature_cols: list[str]) -> float:
    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=True) as tmp:
        joblib.dump({"model": model, "feature_cols": feature_cols, "year": 2025}, tmp.name)
        return os.path.getsize(tmp.name) / (1024 * 1024)


def main() -> None:
    print("[로드] 데이터셋 읽는 중...")
    df = load_dataset(ROOT, 2025)
    id_to_label = load_label_mapping(ROOT)
    feature_cols = get_feature_columns(df)

    train_df, _val_df, test_df = time_based_split(df)
    X_train, y_train = train_df[feature_cols], train_df[TARGET_COL]
    X_test, y_test = test_df[feature_cols], test_df[TARGET_COL]
    print(f"[분할] train={len(train_df):,} test={len(test_df):,}\n")

    print(f"{'설정':<18} {'트리':>5} {'깊이':>5} {'리프':>5} {'크기(MB)':>10} {'top-1':>8} {'top-3':>8} {'학습(s)':>8}")
    print("-" * 76)

    for name, n_estimators, max_depth, min_samples_leaf in CANDIDATES:
        started = time.perf_counter()
        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_jobs=-1,
            random_state=RANDOM_STATE,
        )
        model.fit(X_train, y_train)
        elapsed = time.perf_counter() - started

        y_proba = model.predict_proba(X_test)
        top1 = top_k_accuracy_score(y_test, y_proba, k=1, labels=model.classes_)
        top3 = top_k_accuracy_score(y_test, y_proba, k=3, labels=model.classes_)
        size = model_size_mb(model, feature_cols)

        print(
            f"{name:<18} {n_estimators:>5} {max_depth:>5} {min_samples_leaf:>5} "
            f"{size:>10.1f} {top1:>8.4f} {top3:>8.4f} {elapsed:>8.1f}"
        )


if __name__ == "__main__":
    main()
