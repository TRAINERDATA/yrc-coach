@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [YRC Coach] 패키지 설치 중...
pip install -q -r requirements.txt
echo [YRC Coach] 서버 시작: http://localhost:8000  (Ctrl+C 로 종료)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
