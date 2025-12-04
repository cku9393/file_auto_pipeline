"""
App layer: UI 서버 (FastAPI + HTMX).

역할:
- 채팅 입력, 파일 업로드, 세션 관리
- OCR/LLM 호출, 사용자 확인 UI
- ⚠️ 운영 안전 로직 없음 (core에 위임)

주의: 폴더 구분
- src/app/templates/ → Jinja2 HTML (HTMX)
- src/templates/ → 코드 (manager.py, scaffolder.py)
- templates/ (루트) → 데이터 저장소 (base/, custom/)
"""
