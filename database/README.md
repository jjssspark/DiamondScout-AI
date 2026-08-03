# DiamondScout AI - 서비스 로그 DB (MariaDB)

이 DB는 **서비스 운영 로그 저장용**입니다. Statcast raw 데이터, 전처리 결과(`data/processed/*.csv`),
학습된 모델 파일(`models/*.joblib`, `models/*.keras`) 같은 대용량 학습 데이터는 이 DB에
넣지 않고 지금처럼 파일 그대로 관리합니다. DB에는 사용자가 앱을 사용하면서 발생한
"분석 실행 기록 / Q&A 기록 / 타석 시뮬레이션 투구 기록" 3가지 로그만 쌓입니다.

## 1. MariaDB 설치 및 데이터베이스 생성

MariaDB가 로컬에 설치되어 있어야 합니다 (예: macOS `brew install mariadb && brew services start mariadb`).

```bash
# root로 접속 (설치 시 설정한 비밀번호 입력)
mysql -u root -p
```

> **포트 충돌 시 (예: 이미 다른 MySQL/MariaDB가 3306을 쓰고 있는 경우)**
> `/opt/homebrew/etc/my.cnf`의 `[client-server]`에 `port`/`socket`을 다른 값(예: 3307,
> `/opt/homebrew/var/mysql/mariadb_3307.sock`)으로 지정하고 `brew services restart mariadb`로
> 재시작하면 됩니다. 이 경우 `.env`의 `DB_PORT`도 동일하게 맞춰주세요. Homebrew로 새로 설치한
> MariaDB는 기본적으로 `root` 계정에 비밀번호가 없고 OS 사용자(unix_socket) 인증만 되어 있을 수
> 있으니, TCP 접속용 비밀번호가 필요하면 소켓으로 접속한 뒤 `ALTER USER 'root'@'localhost'
> IDENTIFIED BY '원하는_비밀번호';`로 설정하세요.

`schema.sql`이 `CREATE DATABASE IF NOT EXISTS diamondscout_ai ...`를 포함하고 있어서
데이터베이스를 미리 만들 필요는 없지만, 원하면 아래처럼 먼저 만들어도 됩니다.

```sql
CREATE DATABASE IF NOT EXISTS diamondscout_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 2. schema.sql 실행 방법

프로젝트 루트에서:

```bash
mysql -u root -p < database/schema.sql
```

또는 이미 `mysql` 셸에 접속한 상태라면:

```sql
SOURCE database/schema.sql;
```

정상 실행되면 `diamondscout_ai` 데이터베이스 아래 `analysis_logs`, `qa_logs`,
`simulation_logs` 3개 테이블이 생성됩니다. 이미 존재하면 건너뛰므로(`CREATE TABLE IF NOT EXISTS`)
여러 번 실행해도 안전합니다.

## 3. .env 설정

프로젝트 루트의 `.env.example`을 복사해 `.env`를 만들고 실제 값을 채웁니다.

```bash
cp .env.example .env
```

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=본인이_설정한_비밀번호
DB_NAME=diamondscout_ai
```

`.env`는 절대 커밋/공유하지 마세요. 실제 비밀번호는 코드나 README, `.env.example`
어디에도 하드코딩되어 있지 않습니다 - `.env`에만 존재합니다.

`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_NAME` 중 하나라도 `.env`에 없으면 `services/db_service.py`가
DB 로깅을 자동으로 비활성화하고 콘솔에 경고만 출력합니다. 앱의 예측/분석/Q&A/시뮬레이션
기능은 DB 없이도 항상 정상 동작합니다.

## 4. DBeaver에서 테이블 확인하기

1. DBeaver 실행 → `Database` → `New Database Connection` → **MariaDB** 선택
2. 연결 정보 입력 (`.env`와 동일한 값)
   - Host: `localhost` (또는 `DB_HOST` 값)
   - Port: `3306` (또는 `DB_PORT` 값)
   - Database: `diamondscout_ai`
   - Username / Password: `.env`의 `DB_USER` / `DB_PASSWORD`
3. `Test Connection`으로 연결 확인 후 `Finish`
4. 왼쪽 트리에서 `diamondscout_ai` → `Tables`를 펼치면 `analysis_logs`, `qa_logs`,
   `simulation_logs`가 보입니다. 더블클릭 → `Data` 탭에서 실제 저장된 로그 행을 확인할 수
   있습니다.
5. `context_json`, `top3_json`, `full_result_json` 등은 JSON 컬럼이라 DBeaver의 셀을
   더블클릭하면 포맷된 JSON 뷰어로 열립니다.

## 5. 테이블 요약

| 테이블 | 저장 시점 | 주요 내용 |
|---|---|---|
| `analysis_logs` | "기본 분석" 탭에서 분석 실행 시 | 입력 상황, 최근 5구, Top-3 예측, 위험도 요약, 전체 결과 |
| `qa_logs` | Instant Scout Q&A 질문/답변 시 | 질문, 답변, 답변 출처(ollama/rule_based 등), RAG로 찾은 참고 문서 |
| `simulation_logs` | 타석 시뮬레이션에서 투구 기록 시 | 투구 정보(구종/구속/좌표/결과), 투구 직후 카운트, 타석 종료 여부, 분석 결과 |
