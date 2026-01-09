# NAS 설문 동기화 시스템 설치 가이드

## 1) 사전 준비
- NAS 내부 MariaDB 접근 정보 준비
- Google Service Account 생성 후 `service_account.json` 발급
- Google Sheet 공유 대상에 서비스 계정 이메일 추가

## 2) Python 패키지 설치
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install gspread pymysql flask
```

## 3) MariaDB 테이블 생성
```bash
mysql -u <user> -p <database> < schema.sql
```

## 4) 환경 변수 설정 (예시)
```bash
export DB_HOST=127.0.0.1
export DB_PORT=3306
export DB_USER=nas_user
export DB_PASSWORD=nas_password
export DB_NAME=nas_surveys
export GOOGLE_SERVICE_ACCOUNT=/path/to/service_account.json
export FORMS_CONFIG_PATH=/path/to/forms_config.json
```

## 5) 설문 설정 등록
- `forms_config.json`을 직접 수정하거나
- 웹 UI `/register`에서 입력

## 6) 동기화 실행
### CLI
```bash
python sync_survey.py
```

### Web Admin
```bash
python app.py
```
- 브라우저에서 `http://<NAS_IP>:5000` 접속
- 버튼 클릭 시 동기화 수행

## 7) 주기적 실행 (크론 예시)
```bash
*/10 * * * * /path/to/.venv/bin/python /workspace/nas-auto/sync_survey.py >> /var/log/sync_survey.log 2>&1
```
