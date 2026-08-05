"""무료 티어 호스팅용 축소 RandomForest 학습 · 저장.

프로덕션 모델(models/next_pitch_model.joblib, 188MB)은 512MB 메모리 무료 티어에
올리기 어렵다. scripts/compare_model_sizes.py로 측정한 결과 아래 설정이 크기를
4.9배 줄이면서 top-1 손실 0.55%p / top-3 손실 1.33%p에 그쳐 트레이드오프가 가장 좋았다.

프로덕션 모델은 그대로 두고 배포 전용 아티팩트만 따로 만든다 - 문서에 기재된
대표 성능 수치(top-1 39.5% / top-3 78.7%)는 원본 모델 기준으로 유지하기 위함이다.

저장 형식은 models/next_pitch_model.py의 save_outputs와 동일하므로
services/prediction_service.py가 파일명만 바꿔 끼우면 코드 변경 없이 읽는다.

사용법:
    python scripts/train_deploy_model.py
"""

import os
import sys
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
    time_based_split,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YEAR = 2025
OUTPUT_PATH = os.path.join(ROOT, "models", "next_pitch_model_deploy.joblib")

N_ESTIMATORS = 80
MAX_DEPTH = 14
MIN_SAMPLES_LEAF = 80


def main() -> None:
    print("[로드] 데이터셋 읽는 중...")
    df = load_dataset(ROOT, YEAR)
    feature_cols = get_feature_columns(df)
    train_df, _val_df, test_df = time_based_split(df)
    print(f"[분할] train={len(train_df):,} test={len(test_df):,}")

    print(f"[학습] n_estimators={N_ESTIMATORS} max_depth={MAX_DEPTH} min_samples_leaf={MIN_SAMPLES_LEAF}")
    started = time.perf_counter()
    model = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        min_samples_leaf=MIN_SAMPLES_LEAF,
        n_jobs=-1,
        random_state=RANDOM_STATE,
    )
    model.fit(train_df[feature_cols], train_df[TARGET_COL])
    print(f"[학습] 완료 ({time.perf_counter() - started:.1f}s)")

    y_test = test_df[TARGET_COL]
    y_proba = model.predict_proba(test_df[feature_cols])
    top1 = top_k_accuracy_score(y_test, y_proba, k=1, labels=model.classes_)
    top3 = top_k_accuracy_score(y_test, y_proba, k=3, labels=model.classes_)

    joblib.dump({"model": model, "feature_cols": feature_cols, "year": YEAR}, OUTPUT_PATH)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)

    print(f"\n[저장] {OUTPUT_PATH}")
    print(f"       크기 {size_mb:.1f}MB / top-1 {top1:.4f} / top-3 {top3:.4f}")


if __name__ == "__main__":
    main()
