"""스크립트로 직접 실행하는 진입점이 뜨는지 확인한다.

pytest는 repo 루트를 sys.path에 넣고 돌기 때문에 `from data.x import y` 같은
패키지 경로 import가 깨져도 테스트는 통과한다. 반면 `python data/x.py`로 실행하면
sys.path[0]이 data/라서 같은 import가 ModuleNotFoundError로 죽는다.
실제로 c200826에서 이 방식으로 전처리 CLI가 깨진 채 커밋됐다.

--help만 호출하므로 데이터 파일을 읽거나 쓰지 않는다.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CLI_SCRIPTS = [
    "data/preprocess_statcast.py",
    "data/build_enriched_dataset.py",
]


@pytest.mark.parametrize("script", CLI_SCRIPTS)
def test_cli_script_starts(script):
    result = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, f"{script} 실행 실패:\n{result.stderr}"
