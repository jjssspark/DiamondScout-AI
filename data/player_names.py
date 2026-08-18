"""MLBAM player id -> 이름 룩업 테이블.

Statcast raw의 player_name 컬럼은 **투수 이름만** 담는다. 확인한 근거:
2025-08 표본 123,887구에서 투수 569명 전원이 고유 player_name 1개인 반면,
타자 기준으로 묶으면 1명당 중앙값 42개가 나온다(그 타자를 상대한 투수들의
이름이 섞여 나오는 것이다).

그래서 UI가 타자를 "Batter ID 621566"으로 표시해왔다. 타자 이름은 여기서
따로 만든다.
"""

import glob
import os

import pandas as pd

# 이름을 못 찾았을 때 쓸 문구. services/scouting_service.py가 지금 쓰는 것과 같아야
# 화면에서 폴백 표기가 갈리지 않는다.
_FALLBACK_PREFIX = {"batter": "Batter", "pitcher": "Pitcher"}


def _fallback_label(id_col: str, player_id) -> str:
    prefix = _FALLBACK_PREFIX.get(id_col, id_col.capitalize())
    return f"{prefix} ID {player_id}"


def attach_player_names(profile: pd.DataFrame, names: pd.DataFrame, id_col: str) -> pd.DataFrame:
    """profile의 id_col에 player_name을 붙인다. 못 찾은 id는 "Batter ID {id}"로 채운다.

    left 조인이라 이름이 없어도 행이 사라지지 않는다. inner로 새면 그 타자의 매치업이
    통째로 없어지는데, 화면에는 "데이터 없음"으로 보여 원인 추적이 어렵다.
    """
    lookup = names.drop_duplicates(subset=["player_id"])
    merged = profile.drop(columns=["player_name"], errors="ignore").merge(
        lookup[["player_id", "player_name"]],
        left_on=id_col, right_on="player_id", how="left",
    )
    missing = merged["player_name"].isna()
    merged.loc[missing, "player_name"] = [
        _fallback_label(id_col, pid) for pid in merged.loc[missing, id_col]
    ]
    return merged.drop(columns=["player_id"])


def build_player_name_table(root: str = "data", year: int = 2025) -> pd.DataFrame:
    """해당 연도 raw Statcast에 등장하는 모든 선수의 id -> 이름 표를 만든다.

    투수는 raw의 player_name을 그대로 쓰고, 타자는 pybaseball로 역조회한다.
    조회는 네트워크를 타므로 결과를 CSV로 남겨 두 번 부르지 않는다.
    """
    paths = sorted(glob.glob(os.path.join(root, "raw", f"statcast_{year}-*.csv")))
    if not paths:
        raise FileNotFoundError(f"{root}/raw에 statcast_{year}-*.csv가 없다")

    pitcher_names, batter_ids = [], set()
    for path in paths:
        chunk = pd.read_csv(path, usecols=["player_name", "pitcher", "batter"], low_memory=False)
        pitcher_names.append(chunk[["pitcher", "player_name"]].drop_duplicates())
        batter_ids.update(chunk["batter"].dropna().astype(int).tolist())

    pitchers = (
        pd.concat(pitcher_names)
        .drop_duplicates(subset=["pitcher"])
        .rename(columns={"pitcher": "player_id"})
    )
    pitchers["player_id"] = pitchers["player_id"].astype(int)

    known = set(pitchers["player_id"])
    lookup_ids = sorted(batter_ids - known)
    batters = _lookup_names(lookup_ids)

    table = pd.concat([pitchers, batters], ignore_index=True)
    return table.drop_duplicates(subset=["player_id"]).sort_values("player_id").reset_index(drop=True)


def _lookup_names(player_ids: list[int]) -> pd.DataFrame:
    """pybaseball 역조회. 실패해도 파이프라인을 죽이지 않고 빈 표를 돌려준다 —
    이름이 없으면 attach_player_names가 "Batter ID {id}" 폴백으로 처리한다."""
    if not player_ids:
        return pd.DataFrame(columns=["player_id", "player_name"])

    from pybaseball import playerid_reverse_lookup

    found = playerid_reverse_lookup(player_ids, key_type="mlbam")
    if found.empty:
        return pd.DataFrame(columns=["player_id", "player_name"])

    # Statcast의 player_name과 같은 "Last, First" 형태로 맞춘다.
    names = (
        found["name_last"].fillna("").str.title()
        + ", "
        + found["name_first"].fillna("").str.title()
    )
    return pd.DataFrame({"player_id": found["key_mlbam"].astype(int), "player_name": names})


def save_player_name_table(root: str = "data", year: int = 2025) -> str:
    table = build_player_name_table(root, year)
    out = os.path.join(root, "processed", "player_names.csv")
    table.to_csv(out, index=False)
    return out


if __name__ == "__main__":
    path = save_player_name_table()
    print(f"저장: {path} ({len(pd.read_csv(path)):,}명)")
