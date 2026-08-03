-- DiamondScout AI - 서비스 로그 DB 스키마 (MariaDB)
-- 주의: 이 DB는 학습용 대용량 데이터(raw Statcast, 전처리 결과, 모델 파일)를 저장하지
-- 않는다. 그런 데이터는 지금처럼 data/, models/ 아래 CSV/joblib/keras 파일로 계속 관리하고,
-- 이 DB는 오직 "서비스 사용 로그"(분석 실행 기록, Q&A 기록, 타석 시뮬레이션 기록)만 담는다.

CREATE DATABASE IF NOT EXISTS diamondscout_ai
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE diamondscout_ai;

-- 1) 기본 분석(app.py "기본 분석" 탭, 투수/타자 모드 분석 실행) 로그
CREATE TABLE IF NOT EXISTS analysis_logs (
    id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mode                 VARCHAR(16) NOT NULL,          -- 'pitcher' | 'batter'
    pitcher_id           BIGINT NOT NULL,               -- Statcast pitcher id
    context_json         JSON NOT NULL,                 -- 경기 상황 (balls, strikes, outs_when_up, ...)
    recent_pitches_json  JSON NOT NULL,                 -- 최근 5구 입력값
    user_comment         TEXT NULL,                     -- 사용자 전략 코멘트
    top3_json            JSON NOT NULL,                 -- 다음 구종 Top-3 예측
    risk_summary_json    JSON NOT NULL,                 -- 위험도 요약
    full_result_json     JSON NOT NULL,                 -- ScoutingService.analyze() 전체 반환값
    INDEX idx_analysis_logs_created_at (created_at),
    INDEX idx_analysis_logs_pitcher_id (pitcher_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2) Instant Scout Q&A 질의응답 로그
CREATE TABLE IF NOT EXISTS qa_logs (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    analysis_log_id     BIGINT UNSIGNED NULL,           -- 질문 시점의 최신 analysis_logs.id (없으면 NULL)
    question            TEXT NOT NULL,
    answer              TEXT NOT NULL,
    answer_source       VARCHAR(32) NOT NULL,           -- 'ollama' | 'rule_based' | 'no_analysis' | 'unavailable'
    used_context_json   JSON NULL,                      -- RAG로 검색된 참고 문서 조각
    INDEX idx_qa_logs_created_at (created_at),
    CONSTRAINT fk_qa_logs_analysis_log
        FOREIGN KEY (analysis_log_id) REFERENCES analysis_logs (id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3) 타석 시뮬레이션 투구 기록 로그
CREATE TABLE IF NOT EXISTS simulation_logs (
    id                     BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    pitcher_id             BIGINT NOT NULL,
    mode                   VARCHAR(16) NOT NULL,        -- 'pitcher' | 'batter'
    pitch_label            VARCHAR(8) NOT NULL,         -- FF, SL, CH, ...
    release_speed          DOUBLE NOT NULL,
    plate_x                DOUBLE NOT NULL,
    plate_z                DOUBLE NOT NULL,
    zone_cell              TINYINT NOT NULL,            -- 0~9
    pitch_result           VARCHAR(32) NOT NULL,        -- ball | called_strike | swinging_strike | foul | in_play
    count_json             JSON NOT NULL,                -- 투구 직후 카운트 {balls, strikes, outs_when_up}
    at_bat_over            TINYINT(1) NOT NULL,
    at_bat_outcome         VARCHAR(16) NULL,            -- walk | strikeout | in_play | NULL(진행 중)
    analysis_result_json   JSON NOT NULL,                -- 이 투구 직후 ScoutingService.analyze() 결과
    INDEX idx_simulation_logs_created_at (created_at),
    INDEX idx_simulation_logs_pitcher_id (pitcher_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
