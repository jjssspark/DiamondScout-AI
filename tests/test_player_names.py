import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.player_names import attach_player_names


def test_attaches_name_for_known_id():
    profile = pd.DataFrame({"batter": [111, 222], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({"player_id": [111, 222], "player_name": ["Kim, A", "Lee, B"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert list(result["player_name"]) == ["Kim, A", "Lee, B"]


def test_falls_back_to_id_label_when_name_missing():
    """이름을 못 찾아도 화면에 빈칸이 뜨면 안 된다. 폴백 문구는 앱이 지금 쓰는 것과 같다
    (services/scouting_service.py의 'Batter ID {id}')."""
    profile = pd.DataFrame({"batter": [111, 999], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert result.loc[result["batter"] == 999, "player_name"].iloc[0] == "Batter ID 999"


def test_does_not_drop_rows_when_name_missing():
    """조인이 inner로 새면 이름 없는 타자의 매치업 행이 통째로 사라진다.
    화면에는 '데이터 없음'으로 보이지만 원인은 이름 테이블이라 추적이 어렵다."""
    profile = pd.DataFrame({"batter": [111, 999], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert len(result) == 2


def test_fallback_label_follows_the_id_column():
    """같은 함수를 투수 프로필에도 쓸 수 있어야 한다."""
    profile = pd.DataFrame({"pitcher": [999], "pitch_label": ["FF"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    result = attach_player_names(profile, names, id_col="pitcher")

    assert result["player_name"].iloc[0] == "Pitcher ID 999"


def test_does_not_mutate_the_input_frame():
    profile = pd.DataFrame({"batter": [111], "pitch_label": ["FF"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    attach_player_names(profile, names, id_col="batter")

    assert "player_name" not in profile.columns


def test_duplicate_names_do_not_multiply_rows():
    """이름 테이블에 같은 id가 두 번 들어오면 조인이 행을 불린다.
    프로필 행 수는 입력과 같아야 한다."""
    profile = pd.DataFrame({"batter": [111, 222], "pitch_label": ["FF", "SL"]})
    names = pd.DataFrame({
        "player_id": [111, 111, 222],
        "player_name": ["Kim, A", "Kim, A", "Lee, B"],
    })

    result = attach_player_names(profile, names, id_col="batter")

    assert len(result) == 2


def test_overwrites_an_existing_name_column():
    """preprocess를 두 번 돌려도 player_name이 겹쳐 _x/_y로 갈라지면 안 된다."""
    profile = pd.DataFrame({"batter": [111], "pitch_label": ["FF"], "player_name": ["헌 값"]})
    names = pd.DataFrame({"player_id": [111], "player_name": ["Kim, A"]})

    result = attach_player_names(profile, names, id_col="batter")

    assert list(result["player_name"]) == ["Kim, A"]
    assert "player_name_x" not in result.columns
