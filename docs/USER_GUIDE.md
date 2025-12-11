# File Auto Pipeline - 사용자 가이드

제조 현장 검사 문서 자동 생성 시스템

---

## 목차

1. [개요](#개요)
2. [설치](#설치)
3. [설정](#설정)
4. [사용 방법](#사용-방법)
5. [API 레퍼런스](#api-레퍼런스)
6. [FAQ](#faq)
7. [문제 해결](#문제-해결)

---

## 개요

File Auto Pipeline은 제조 현장에서 검사 데이터를 자연어 또는 이미지로 입력받아 자동으로 검사 보고서(DOCX)와 측정 데이터(XLSX)를 생성하는 시스템입니다.

### 주요 기능

- 📝 **대화형 입력**: 자연어로 작업 정보 입력
- 📷 **OCR 지원**: 이미지에서 자동으로 텍스트 추출 (Gemini API)
- 🤖 **AI 필드 추출**: Claude API를 통한 지능형 데이터 추출
- ✅ **자동 검증**: definition.yaml 기반 필드 유효성 검사
- 📄 **문서 생성**: Word 보고서 및 Excel 측정 데이터 자동 생성

### 시스템 요구사항

- Python 3.11 이상
- Linux, macOS, Windows (WSL2)
- 8GB RAM 이상 권장
- 디스크 여유 공간 1GB 이상

---

## 설치

### 1. 저장소 클론

```bash
git clone https://github.com/your-org/file_auto_pipline.git
cd file_auto_pipline
```

### 2. Python 가상환경 설정

```bash
# uv 설치 (권장)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 의존성 설치
uv sync
```

또는 pip 사용:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. 환경 변수 설정

`.env` 파일 생성:

```bash
cp .env.example .env
```

`.env` 파일 편집:

```env
# Anthropic Claude API
# ⚠️ 이 프로젝트는 MY_ANTHROPIC_KEY만 사용합니다 (ANTHROPIC_API_KEY 아님)
#    Claude Code 등 외부 도구와 키 네임스페이스가 섞이지 않도록 분리했습니다.
MY_ANTHROPIC_KEY=sk-ant-xxxxxxxxxxxxx

# Google Gemini API
GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxxx

# Optional: 로깅 레벨
LOG_LEVEL=INFO
```

### 4. 서버 실행

```bash
uv run uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

서버가 정상적으로 시작되면 http://localhost:8000 에서 접속 가능합니다.

---

## 설정

### definition.yaml

필드 정의 및 검증 규칙을 설정합니다:

```yaml
# config/definition.yaml
fields:
  wo_no:
    type: string
    importance: critical
    override_allowed: false
    description: "작업 지시 번호"
    aliases: ["WO No", "작업번호", "워크오더"]

  line:
    type: string
    importance: critical
    override_allowed: false
    description: "라인명"
    aliases: ["Line", "라인"]

  # ... 추가 필드 정의
```

### 템플릿 설정

`templates/base/manifest.yaml`에서 문서 템플릿 매핑을 설정:

```yaml
template_id: base
display_name: "기본 템플릿"

# DOCX 플레이스홀더
docx_placeholders:
  - wo_no
  - line
  - part_no
  - lot
  - result

# XLSX Named Ranges
xlsx_mappings:
  named_ranges:
    wo_no: "WO_NO"
    line: "LINE"
  # ... 추가 매핑
```

---

## 사용 방법

### 웹 인터페이스

1. **브라우저에서 접속**
   ```
   http://localhost:8000/chat
   ```

2. **작업 정보 입력**

   자연어로 작업 정보를 입력합니다:
   ```
   WO No: WO-001, Line: L1, Part No: PART-A, LOT: LOT-2024-001,
   Inspector: 홍길동, Result: PASS, Date: 2024-12-04
   ```

3. **파일 첨부 (선택사항)**

   📎 버튼을 클릭하여 이미지나 문서를 첨부할 수 있습니다.
   - 지원 형식: JPG, PNG, PDF, Excel, 텍스트
   - 이미지 파일은 자동으로 OCR 처리됩니다

4. **필드 추출**

   입력이 완료되면 "추출" 버튼을 클릭합니다.
   시스템이 자동으로:
   - 입력 데이터 파싱
   - 필드 추출
   - 유효성 검증

5. **문서 생성**

   추출 결과가 올바르면 "문서 생성" 버튼을 클릭합니다.
   - DOCX: 제조 검사 보고서
   - XLSX: 측정 데이터 시트

### API 사용

#### 1. 메시지 전송

```bash
curl -X POST http://localhost:8000/api/chat/message \
  -F "content=WO No: WO-001, Line: L1, Part No: PART-A, LOT: LOT-2024-001, Result: PASS" \
  -F "session_id=my-session-123"
```

#### 2. 파일 업로드

```bash
curl -X POST http://localhost:8000/api/chat/upload \
  -F "file=@inspection_photo.jpg" \
  -F "session_id=my-session-123"
```

#### 3. 필드 추출

```bash
curl -X POST http://localhost:8000/api/chat/extract \
  -F "session_id=my-session-123"
```

응답 예시:
```json
{
  "success": true,
  "fields": {
    "wo_no": "WO-001",
    "line": "L1",
    "part_no": "PART-A",
    "lot": "LOT-2024-001",
    "result": "PASS"
  },
  "validation": {
    "valid": true,
    "missing_required": [],
    "invalid_values": []
  }
}
```

#### 4. 문서 생성

```bash
curl -X POST http://localhost:8000/api/generate \
  -F "session_id=my-session-123" \
  -F "template_id=base" \
  -F "output_format=both"
```

응답 예시:
```json
{
  "success": true,
  "job_id": "JOB-ABC12345",
  "files": [
    {"name": "report.docx", "size": 37000},
    {"name": "measurements.xlsx", "size": 5300}
  ],
  "download_url": "/api/generate/jobs/JOB-ABC12345/download"
}
```

#### 5. 파일 다운로드

```bash
# 개별 파일
curl -O http://localhost:8000/api/generate/jobs/JOB-ABC12345/download/report.docx

# 전체 ZIP
curl -O http://localhost:8000/api/generate/jobs/JOB-ABC12345/download
```

---

## API 레퍼런스

### 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |
| GET | `/chat` | 채팅 UI 페이지 |
| POST | `/api/chat/message` | 메시지 전송 |
| POST | `/api/chat/upload` | 파일 업로드 |
| POST | `/api/chat/extract` | 필드 추출 |
| POST | `/api/generate` | 문서 생성 |
| GET | `/api/generate/jobs` | 작업 목록 조회 |
| GET | `/api/generate/jobs/{job_id}` | 작업 상세 조회 |
| GET | `/api/generate/jobs/{job_id}/download/{filename}` | 파일 다운로드 |

### 상세 명세

#### POST /api/chat/extract

필드 추출 및 검증을 수행합니다.

**요청 파라미터:**
- `session_id` (required): 세션 ID

**응답:**
```json
{
  "success": true,
  "fields": {
    "wo_no": "string",
    "line": "string",
    "part_no": "string",
    "lot": "string",
    "result": "PASS|FAIL"
  },
  "measurements": [
    {
      "item": "string",
      "measured": "number",
      "unit": "string",
      "result": "PASS|FAIL"
    }
  ],
  "missing_fields": [],
  "warnings": [],
  "confidence": 0.95,
  "model_used": "claude-opus-4-5-20251101",
  "validation": {
    "valid": true,
    "missing_required": [],
    "invalid_values": [],
    "overridable": []
  }
}
```

#### POST /api/generate

DOCX/XLSX 문서를 생성합니다.

**요청 파라미터:**
- `session_id` (required): 세션 ID
- `template_id` (optional): 템플릿 ID (기본값: "base")
- `output_format` (optional): 출력 형식 "docx"|"xlsx"|"both" (기본값: "both")

**응답:**
```json
{
  "success": true,
  "job_id": "JOB-ABC12345",
  "files": [
    {
      "name": "report.docx",
      "size": 37000,
      "path": "JOB-ABC12345/deliverables/report.docx"
    }
  ],
  "download_url": "/api/generate/jobs/JOB-ABC12345/download",
  "message": "문서가 생성되었습니다!"
}
```

---

## FAQ

### Q1. OCR이 정확하지 않아요

**A:** OCR 품질은 이미지 품질에 크게 영향을 받습니다:
- 해상도: 최소 300 DPI 이상 권장
- 조명: 균일하고 충분한 조명
- 각도: 정면에서 촬영
- 흐림: 초점이 맞은 선명한 이미지

OCR 신뢰도가 0.8 미만이면 경고 메시지가 표시됩니다.

### Q2. 필드 추출이 실패해요

**A:** 다음을 확인하세요:
1. **API 키**: `.env` 파일에 MY_ANTHROPIC_KEY가 올바르게 설정되었는지
2. **입력 형식**: 필드명과 별칭을 definition.yaml에서 확인
3. **필수 필드**: wo_no, line, part_no, lot, result는 반드시 포함

예시:
```
✅ 올바른 형식:
WO No: WO-001, Line: L1, Part No: PART-A, LOT: LOT-2024-001, Result: PASS

❌ 잘못된 형식:
작업번호는 WO-001이고 라인은 L1입니다
```

### Q3. 문서 생성이 실패해요

**A:** 가능한 원인:
1. **템플릿 파일 누락**: `templates/base/` 디렉토리에 템플릿 파일 확인
2. **필드 검증 실패**: 필수 필드가 모두 추출되었는지 확인
3. **권한 문제**: `jobs/` 디렉토리에 쓰기 권한 확인

로그 확인:
```bash
tail -f /tmp/server.log
```

### Q4. 세션이 사라졌어요

**A:** 현재 버전은 인메모리 세션을 사용합니다:
- 서버 재시작 시 세션 초기화
- 프로덕션 환경에서는 Redis나 데이터베이스 사용 권장

세션 데이터는 `jobs/JOB-*/inputs/intake_session.json`에 영구 저장됩니다.

### Q5. Named Range가 작동하지 않아요

**A:** Excel 템플릿에서 Named Range 설정을 확인하세요:
1. Excel에서 템플릿 열기
2. 수식 탭 → 이름 관리자
3. `manifest.yaml`의 named_ranges와 일치하는지 확인

예시:
```yaml
# manifest.yaml
named_ranges:
  wo_no: "WO_NO"  # Excel에서 "WO_NO" Named Range 존재해야 함
```

---

## 문제 해결

### 일반적인 오류

#### 1. "Address already in use" 에러

**문제:** 포트 8000이 이미 사용 중입니다.

**해결:**
```bash
# 기존 프로세스 종료
pkill -f "uvicorn src.app.main:app"

# 또는 다른 포트 사용
uv run uvicorn src.app.main:app --port 8001
```

#### 2. "MY_ANTHROPIC_KEY not found" 에러

**문제:** API 키가 설정되지 않았습니다.

**해결:**
```bash
# .env 파일 확인
cat .env | grep MY_ANTHROPIC_KEY

# 없으면 추가
echo "MY_ANTHROPIC_KEY=sk-ant-your-key-here" >> .env
```

#### 3. "Template not found" 에러

**문제:** 템플릿 파일이 없습니다.

**해결:**
```bash
# 템플릿 디렉토리 확인
ls templates/base/

# 필요한 파일:
# - report_template.docx
# - measurements_template.xlsx
# - manifest.yaml
```

템플릿 생성 스크립트:
```bash
uv run python scripts/create_templates.py
```

#### 4. "Validation failed" 에러

**문제:** 필수 필드가 누락되었습니다.

**해결:**

에러 메시지에서 누락된 필드 확인:
```json
{
  "validation": {
    "valid": false,
    "missing_required": ["lot"]
  }
}
```

해당 필드를 입력에 추가:
```
LOT: LOT-2024-001
```

### 로그 확인

**서버 로그:**
```bash
tail -100 /tmp/server.log
```

**특정 에러 검색:**
```bash
grep ERROR /tmp/server.log
grep Traceback /tmp/server.log
```

**실시간 모니터링:**
```bash
tail -f /tmp/server.log
```

### 디버깅 모드

더 자세한 로그를 보려면:

```bash
# .env 파일에 추가
LOG_LEVEL=DEBUG

# 서버 재시작
```

---

## 고급 사용법

### 커스텀 템플릿 생성

1. 새 템플릿 디렉토리 생성:
```bash
mkdir templates/my_template
```

2. 템플릿 파일 준비:
```
templates/my_template/
├── report_template.docx
├── measurements_template.xlsx
└── manifest.yaml
```

3. manifest.yaml 작성:
```yaml
template_id: my_template
display_name: "나의 템플릿"
doc_type: inspection

docx_placeholders:
  - wo_no
  - custom_field

xlsx_mappings:
  named_ranges:
    custom_field: "CUSTOM_FIELD"
```

4. API에서 사용:
```bash
curl -X POST http://localhost:8000/api/generate \
  -F "session_id=my-session" \
  -F "template_id=my_template"
```

### 배치 처리

여러 작업을 한 번에 처리:

```python
import requests

sessions = []

# 1. 메시지 전송
for i, data in enumerate(batch_data):
    session_id = f"batch-{i}"
    sessions.append(session_id)

    requests.post(
        "http://localhost:8000/api/chat/message",
        data={"content": data, "session_id": session_id}
    )

# 2. 추출 및 생성
for session_id in sessions:
    # 추출
    requests.post(
        "http://localhost:8000/api/chat/extract",
        data={"session_id": session_id}
    )

    # 생성
    response = requests.post(
        "http://localhost:8000/api/generate",
        data={"session_id": session_id}
    )

    print(f"Generated: {response.json()['job_id']}")
```

---

## 지원

- 📧 이메일: support@example.com
- 💬 Discord: https://discord.gg/example
- 🐛 이슈 리포트: https://github.com/your-org/file_auto_pipline/issues
- 📖 문서: https://docs.example.com

---

## 라이선스

MIT License - 자세한 내용은 LICENSE 파일 참조

---

**마지막 업데이트:** 2024-12-04
**버전:** 1.0.0
