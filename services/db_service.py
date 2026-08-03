"""
DiamondScout AI - DB 로깅 서비스
분석(analysis_logs)/질의응답(qa_logs)/타석 시뮬레이션(simulation_logs) 결과를 MariaDB에
저장한다. raw Statcast 데이터나 모델 학습 데이터는 여기서 다루지 않으며(파일 기반 그대로
유지), DB는 오직 서비스 사용 로그 저장용이다.

연결 정보는 .env(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)에서 읽는다. DB가 설정되지
않았거나 연결/저장에 실패해도 예외를 호출자에게 전파하지 않는다 - 콘솔 경고만 남기고
None을 반환해, DB 없이도 앱의 핵심 기능(예측/분석/Q&A/시뮬레이션)은 항상 정상 동작해야 한다.
"""

import json
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()


def _load_db_config() -> dict | None:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, name]):
        return None
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": name,
    }


class DBService:
    """MariaDB 서비스 로그 저장소. save_* 메서드는 성공 시 insert된 행의 id(int)를,
    DB 미설정/연결 실패/저장 실패 시 None을 반환하며 절대 예외를 던지지 않는다."""

    def __init__(self):
        self.config = _load_db_config()
        self.enabled = self.config is not None
        if not self.enabled:
            print("[경고] .env에 DB_HOST/DB_PORT/DB_USER/DB_NAME이 설정되지 않아 DB 로깅을 사용하지 않습니다.")
            return

        # 시작 시 연결 가능 여부만 한 번 확인한다. 이후 개별 저장 시점에도 실패하면
        # 그때그때 경고만 남기고 넘어간다(연결이 끊겼다가 복구되는 경우를 허용하기 위함).
        try:
            self._connect().close()
        except Exception as exc:  # noqa: BLE001 - DB 드라이버 예외는 다양하게 발생할 수 있음
            print(f"[경고] MariaDB 연결 실패, DB 로깅 없이 서비스 기능은 계속 동작합니다: {exc}")
            self.enabled = False

    def _connect(self):
        return pymysql.connect(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=3,
        )

    def _execute(self, sql: str, params: tuple) -> int | None:
        if not self.enabled:
            return None
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.lastrowid
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            print(f"[경고] DB 저장 실패 (서비스는 계속 동작합니다): {exc}")
            return None

    def save_analysis_log(
        self, mode: str, pitcher_id: int, context: dict, recent_pitches: list[dict],
        user_comment: str, result: dict,
    ) -> int | None:
        sql = (
            "INSERT INTO analysis_logs "
            "(mode, pitcher_id, context_json, recent_pitches_json, user_comment, "
            "top3_json, risk_summary_json, full_result_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        )
        params = (
            mode,
            pitcher_id,
            json.dumps(context, ensure_ascii=False),
            json.dumps(recent_pitches, ensure_ascii=False),
            user_comment,
            json.dumps(result.get("predicted_top3_pitches"), ensure_ascii=False),
            json.dumps(result.get("risk_summary"), ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
        )
        return self._execute(sql, params)

    def save_qa_log(
        self, question: str, answer: str, answer_source: str,
        used_context: list[str], analysis_log_id: int | None = None,
    ) -> int | None:
        sql = (
            "INSERT INTO qa_logs (analysis_log_id, question, answer, answer_source, used_context_json) "
            "VALUES (%s, %s, %s, %s, %s)"
        )
        params = (analysis_log_id, question, answer, answer_source, json.dumps(used_context, ensure_ascii=False))
        return self._execute(sql, params)

    def save_simulation_log(
        self, pitcher_id: int, mode: str, pitch_record: dict, count: dict,
        at_bat_over: bool, at_bat_outcome: str | None, analysis_result: dict,
    ) -> int | None:
        sql = (
            "INSERT INTO simulation_logs "
            "(pitcher_id, mode, pitch_label, release_speed, plate_x, plate_z, zone_cell, pitch_result, "
            "count_json, at_bat_over, at_bat_outcome, analysis_result_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        params = (
            pitcher_id,
            mode,
            pitch_record["pitch_label"],
            pitch_record["release_speed"],
            pitch_record["plate_x"],
            pitch_record["plate_z"],
            pitch_record["zone_cell"],
            pitch_record["result"],
            json.dumps(count, ensure_ascii=False),
            bool(at_bat_over),
            at_bat_outcome,
            json.dumps(analysis_result, ensure_ascii=False),
        )
        return self._execute(sql, params)
