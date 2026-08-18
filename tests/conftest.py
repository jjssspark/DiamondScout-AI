"""TS-010: keras(TensorFlow)를 pandas/pyarrow보다 먼저 로드시킨다.

pytest는 테스트 모듈보다 conftest를 먼저 import 하므로, 여기서 keras를 먼저 잡아 두면
수집 순서와 무관하게 TF가 pyarrow보다 앞서 로드된다.

이게 없으면 파일 하나씩 돌릴 때는 전부 통과하지만 전체 스위트는 교착한다. 알파벳순
수집에서 test_feature_builders(-> pandas -> pyarrow)가 test_seq_infer(-> keras)보다
먼저 오기 때문이다. 원인은 TROUBLESHOOTING.md TS-010 참고.

배포 환경에는 TensorFlow가 없다. 없으면 그냥 넘어간다 - 그 환경에서는 keras를 쓰는
테스트 자체가 importorskip으로 건너뛰므로 교착도 일어나지 않는다.
"""

try:
    import keras  # noqa: F401
except ImportError:
    pass
