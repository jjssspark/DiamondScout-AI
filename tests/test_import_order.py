"""TS-010 회귀 방지: TensorFlow가 pyarrow보다 먼저 로드돼야 한다.

pyarrow와 TensorFlow는 둘 다 absl 심볼을 weak definition으로 내보낸다. macOS dyld는
weak 정의를 이미지 간에 하나로 합치고 먼저 로드된 쪽이 이기므로, pyarrow가 먼저
로드되면 TF가 Arrow판 absl 뮤텍스를 쓰게 되고 첫 eager 연산에서 영원히 멈춘다.
예외도 없고 CPU도 0%라 실패가 조용하다 - 그래서 테스트로 못 박아 둔다.

실제로 import 해서 확인하면 이 테스트 프로세스 자체가 교착할 수 있으므로,
소스의 import 순서만 정적으로 검사한다.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# TF를 쓰면서 parquet도 읽는 스크립트. 여기에 추가되는 파일은 같은 규칙을 지켜야 한다.
TF_SCRIPTS = ["scripts/train_seq.py"]

PYARROW_MODULES = {"pandas", "pyarrow"}
TF_MODULES = {"keras", "tensorflow"}


def _module_import_lines(path: Path) -> list[tuple[int, str]]:
    """모듈 최상단(함수 밖) import만 (줄번호, 최상위 모듈명)으로 뽑는다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


@pytest.mark.parametrize("script", TF_SCRIPTS)
def test_tensorflow_imported_before_pyarrow(script):
    imports = _module_import_lines(ROOT / script)

    tf_lines = [n for n, m in imports if m in TF_MODULES]
    pa_lines = [n for n, m in imports if m in PYARROW_MODULES]

    assert tf_lines, f"{script}: keras/tensorflow를 모듈 최상단에서 import 해야 한다 (TS-010)"
    assert pa_lines, f"{script}: pandas/pyarrow import가 사라졌다. TF_SCRIPTS 목록을 갱신할 것"
    assert min(tf_lines) < min(pa_lines), (
        f"{script}: pandas/pyarrow(line {min(pa_lines)})가 "
        f"keras/tensorflow(line {min(tf_lines)})보다 먼저 import 된다. "
        "이 순서면 학습이 예외 없이 교착한다 - TS-010 참고"
    )
