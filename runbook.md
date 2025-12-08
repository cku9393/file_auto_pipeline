# Runbook - 운영 매뉴얼

제조 문서화 파이프라인 운영 가이드입니다.

> **확장 기능**: 채팅 UI, AI 파싱, 템플릿 라이브러리 등은  
> [spec-v2.md](./spec-v2.md)를 참조하세요.

---

## 명령어 상태

### ✅ Current (현재 동작)

| 명령어 | 설명 | 상태 |
|--------|------|:----:|
| `uv run python -m src.app.main` | 웹 UI 서버 (개발 모드) | ✅ |
| `uv run uvicorn src.app.main:app --reload` | 개발 서버 (auto-reload) | ✅ |
| `uv run pytest tests/` | 전체 테스트 실행 | ✅ |
| `uv run pytest tests/unit/` | 유닛 테스트 실행 | ✅ |
| `uv run pytest tests/integration/` | 통합 테스트 실행 | ✅ |
| `uv run pytest tests/e2e/` | E2E 테스트 실행 | ✅ |

### 🔜 Planned (예정)

| 명령어 | 설명 | 예정 시점 |
|--------|------|-----------|
| `uv run generate` | CLI 보고서 생성 | Phase 6 |
| `uv run register-template` | 템플릿 등록 CLI | Phase 6 |

> 구현 완료 시 이 섹션을 업데이트합니다.

---

## 목차

1. [일상 운영](#1-일상-운영)
2. [테스트 실행](#2-테스트-실행)
3. [에러 대응](#3-에러-대응)
   - [3.5. Override Reason 품질 검증](#35-override-reason-품질-검증)
   - [3.6. 사진 처리 파이프라인](#36-사진-처리-파이프라인)
   - [3.7. 사진 슬롯 매칭 신뢰도](#37-사진-슬롯-매칭-신뢰도)
   - [3.8. _trash 보관 정책 및 Purge](#38-_trash-보관-정책-및-purge)
   - [3.9. Generate 동시성 보호](#39-generate-동시성-보호)
   - [3.10. AI Raw 데이터 저장 정책](#310-ai-raw-데이터-저장-정책)
   - [3.11. 골든 테스트 정책](#311-골든-테스트-정책)
4. [경고 대응](#4-경고-대응)
5. [락 문제 해결](#5-락-문제-해결)
6. [백업 및 복구](#6-백업-및-복구)
7. [긴급 대응](#7-긴급-대응)
8. [트러블슈팅](#8-트러블슈팅)

---

## 1. 일상 운영

### 1.1 파이프라인 실행

```bash
# 웹 UI 서버 실행 (권장)
uv run uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000

# CLI 실행 (Planned - 현재 웹 API 사용)
# uv run python -m src.cli.generate jobs/<job_folder>

# 프로덕션 서버
uv run uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

> **Note**: CLI 명령어는 Phase 6에서 구현 예정. 현재는 웹 API(`/api/generate`)를 사용합니다.

### 1.2 실행 전 체크리스트

| # | 확인 사항 | 명령어/방법 |
|---|-----------|-------------|
| 1 | packet.xlsx 존재 | `ls jobs/<folder>/packet.xlsx` |
| 2 | 필수 사진 존재 | `ls jobs/<folder>/photos/raw/01_overview.* 02_label_serial.*` |
| 3 | 디스크 공간 | `df -h` (최소 100MB 권장) |
| 4 | 락 없음 | `ls -la jobs/<folder>/.lock` (없어야 정상) |
| 5 | _trash 용량 확인 | `du -sh jobs/<folder>/photos/_trash/` (100MB 미만 권장) |

### 1.2.1 주간/월간 정기 점검

| 주기 | 작업 | 명령어 |
|------|------|--------|
| 주간 | _trash 용량 확인 | `du -sh jobs/*/photos/_trash/` |
| 주간 | 경고 로그 확인 | `grep -r '"code":"PHOTO' jobs/*/logs/*.json \| wc -l` |
| 월간 | _trash purge 실행 | `uv run python scripts/purge_trash.py --execute` |
| 월간 | 아카이브 용량 확인 | `du -sh jobs/*/photos/_archive/` |

### 1.3 실행 결과 확인

```bash
# 성공 시 생성되는 파일
jobs/<folder>/
├── job.json                      # SSOT (job_id 포함)
├── logs/
│   └── run_<run_id>.json         # 실행 로그 (run_id 앞 8자리)
└── deliverables/
    ├── report.html               # 보고서
    └── report.pdf                # (--pdf 옵션 시)
```

**성공 판정:**
```bash
# 최근 로그에서 결과 확인
cat jobs/<folder>/logs/run_*.json | jq '.result'
# "success" 또는 "rejected"
```

### 1.4 로그 모니터링

```bash
# 최근 실행 로그 확인
ls -lt jobs/<folder>/logs/ | head -5

# 특정 실행의 경고 확인
cat jobs/<folder>/logs/run_*.json | jq '.warnings[]'

# reject 이유 확인
cat jobs/<folder>/logs/run_*.json | jq '{result, reject_reason, reject_context}'

# 전체 로그 요약
cat jobs/<folder>/logs/run_*.json | jq '{job_id, run_id, result, warnings: (.warnings | length)}'
```

---

## 2. 테스트 실행

### 2.1 테스트 구조

```
tests/
├── unit/                    # 유닛 테스트 (490+ 테스트)
│   ├── test_core/          # Core 모듈 (130+ 테스트)
│   ├── test_render/        # Render 모듈 (28 테스트)
│   ├── test_templates/     # Templates 모듈 (53 테스트)
│   ├── test_app/           # App 모듈 (157 테스트)
│   └── test_scripts/       # Scripts 테스트 (10 테스트)
├── integration/            # 통합 테스트
│   ├── test_pipeline_flow.py    # 전체 파이프라인 흐름
│   └── test_chat_to_document.py # 채팅→문서 생성
└── e2e/                    # E2E 테스트
    ├── test_api_chat.py    # Chat API 테스트
    ├── test_api_generate.py # Generate API 테스트
    └── test_api_templates.py # Templates API 테스트
```

### 2.2 테스트 실행

```bash
# 전체 테스트 실행
uv run pytest tests/

# 특정 모듈만 실행
uv run pytest tests/unit/test_core/     # Core 모듈
uv run pytest tests/unit/test_app/      # App 모듈
uv run pytest tests/integration/        # 통합 테스트
uv run pytest tests/e2e/                # E2E 테스트

# 특정 테스트 파일
uv run pytest tests/unit/test_core/test_ssot_job.py

# 특정 테스트 함수
uv run pytest tests/unit/test_core/test_ssot_job.py::TestEnsureJobJson::test_creates_job_folder

# 키워드로 필터링
uv run pytest -k "ssot" tests/          # "ssot" 포함 테스트만

# 상세 출력
uv run pytest tests/ -v --tb=long

# 실패 시 즉시 중단
uv run pytest tests/ -x

# 커버리지 포함
uv run pytest tests/ --cov=src --cov-report=html
```

### 2.3 테스트 유형별 특징

| 유형 | 특징 | 실행 시간 | 의존성 |
|------|------|-----------|--------|
| **Unit** | 개별 함수/클래스 격리 테스트 | 빠름 (~30초) | 최소 |
| **Integration** | 모듈 간 협력 검증, Mock 사용 | 보통 (~1분) | Mock |
| **E2E** | FastAPI 엔드포인트 전체 흐름 | 느림 (~2분) | TestClient |

### 2.4 테스트 작성 규칙

**ADR-0003 준수 사항:**
```python
# 1. model_requested + model_used 필수
result = ExtractionResult(
    success=True,
    fields={"wo_no": "WO-001"},
    model_requested="claude-opus-4-5-20251101",  # 필수
    model_used="claude-opus-4-5-20251101",        # 필수
)

# 2. PolicyRejectError 검증
with pytest.raises(PolicyRejectError) as exc_info:
    service.add_extraction_result(duplicate)
assert exc_info.value.code == ErrorCodes.INTAKE_IMMUTABLE_VIOLATION
assert "overwrite" in str(exc_info.value).lower()  # .message 아님!

# 3. 정규식 우선 원칙
# ExtractionService는 정규식 결과가 LLM 결과보다 우선
```

### 2.5 일반적인 테스트 문제

| 문제 | 원인 | 해결 |
|------|------|------|
| `ModuleNotFoundError` | PYTHONPATH 미설정 | `uv run pytest` 사용 |
| `async def not supported` | pytest-asyncio 미설치 | `uv sync --all-extras` |
| `fixture not found` | conftest.py 누락 | 상위 디렉터리 확인 |
| 테스트 격리 실패 | tmp_path 미사용 | pytest의 `tmp_path` fixture 활용 |

### 2.6 Mock 및 데이터클래스 주의사항

#### MagicMock 자동 속성 생성

```python
# ❌ 잘못된 사용 - mock.model이 MagicMock 객체가 됨
mock_response = MagicMock()
mock_response.content[0].text = '{"fields": {}}'
# mock_response.model → <MagicMock> (문자열 아님!)

# ✅ 올바른 사용 - factory 함수 사용
from tests.unit.test_app.test_providers.test_anthropic import make_anthropic_response

mock_response = make_anthropic_response(
    text='{"fields": {}}',
    model="claude-opus-4-5-20251101",
    request_id="msg_123",
)
```

#### ExtractionResult.to_dict() None 필터링 정책

**주의**: `ExtractionResult.to_dict()`는 None 값을 제거합니다 (용량 절약 목적).

```python
# 기본 ExtractionResult의 to_dict() 결과
result = ExtractionResult()
d = result.to_dict()
# d.keys() == {'success', 'fields', 'measurements', 'missing_fields', 'warnings', 'llm_raw_truncated'}
# None인 model_requested, model_used, confidence 등은 포함되지 않음!

# 테스트에서 expected_keys 비교 시 주의
expected_keys = {"success", "fields", ...}  # None 값 필드 제외
assert set(d.keys()) == expected_keys
```

이 정책은 `src/app/providers/base.py:250`에서 구현됨:
```python
return {k: v for k, v in result.items() if v is not None}
```

---

## 3. 에러 대응

### 에러 코드 Quick Reference

| 코드 | 원인 | 긴급도 | 대응 |
|------|------|--------|------|
| `MISSING_CRITICAL_FIELD` | 필수 필드 누락 | 🔴 높음 | packet.xlsx 수정 |
| `INVALID_DATA` | NaN/Inf 감지 | 🔴 높음 | 측정값 확인 |
| `PARSE_ERROR_CRITICAL` | 필수 필드 파싱 실패 | 🔴 높음 | 데이터 형식 확인 |
| `MISSING_REQUIRED_PHOTO` | 필수 사진 누락 | 🔴 높음 | photos/raw/ 확인 |
| `PHOTO_REQUIRED_MISSING` | 필수 슬롯 사진 없음 (override 불가) | 🔴 높음 | 사진 업로드 필요 |
| `PHOTO_OVERRIDE_REQUIRED` | 필수 슬롯 사진 없음 (override 가능) | 🟡 중간 | 사진 또는 override 사유 제공 |
| `JOB_JSON_LOCK_TIMEOUT` | 락 획득 실패 (동시 접근) | 🟡 중간 | [3.9 동시성 보호](#39-generate-동시성-보호) 참조 |
| `PACKET_JOB_MISMATCH` | WO/Line 불일치 | 🟡 중간 | 올바른 폴더 확인 |
| `ARCHIVE_FAILED` | 아카이브 실패 | 🔴 높음 | 디스크/권한 확인 |
| `INVALID_OVERRIDE_REASON` | override 사유 품질 미달 | 🟡 중간 | [3.5 Override 품질](#35-override-reason-품질-검증) 참조 |

### 2.1 MISSING_CRITICAL_FIELD

**증상:**
```
PolicyRejectError: MISSING_CRITICAL_FIELD
  field: wo_no
```

**원인:** packet.xlsx에서 필수 필드(wo_no, line, part_no, lot, result 중 하나)를 찾을 수 없음

**해결:**
1. packet.xlsx 열기
2. 해당 필드명 또는 별칭(aliases) 확인
   - `wo_no` 별칭: WO, 작업지시, Work Order 등
   - 전체 목록: `definition.yaml` 참조
3. 셀 값이 비어있지 않은지 확인
4. 파이프라인 재실행

### 2.2 INVALID_DATA

**증상:**
```
PolicyRejectError: INVALID_DATA
  field: measured
  value: NaN
```

**원인:** 측정 테이블에 NaN 또는 Inf 값 존재

**해결:**
1. packet.xlsx의 측정 테이블 확인
2. `#DIV/0!`, `#VALUE!`, `#REF!` 등 Excel 에러 수정
3. 빈 셀에 실제 측정값 입력
4. 파이프라인 재실행

### 2.3 PARSE_ERROR_CRITICAL

**증상:**
```
PolicyRejectError: PARSE_ERROR_CRITICAL
  field: date
  raw_value: "내일"
```

**원인:** 필수 필드 값을 지정된 타입으로 파싱 불가

**해결:**
1. `definition.yaml`에서 해당 필드의 `type` 확인
   - `token`: 공백 제거된 문자열
   - `number`: 숫자 (소수점 허용)
   - `date`: ISO 형식 또는 Excel 날짜
2. packet.xlsx에서 올바른 형식으로 수정
3. 파이프라인 재실행

### 2.4 MISSING_REQUIRED_PHOTO

**증상:**
```
PolicyRejectError: MISSING_REQUIRED_PHOTO
  slot: overview
  expected: 01_overview.jpg (or .jpeg, .png)
```

**원인:** 필수 사진 슬롯에 해당하는 파일이 없음

**해결:**
1. photos/raw/ 폴더 확인
   ```bash
   ls -la jobs/<folder>/photos/raw/
   ```
2. 필수 슬롯 확인 (`definition.yaml` 기준):
   - `01_overview.*` (required)
   - `02_label_serial.*` (required)
3. 파일명이 정확한지 확인 (대소문자, 확장자)
4. 누락된 사진 추가 후 재실행

### 2.5 PACKET_JOB_MISMATCH

**증상:**
```
PolicyRejectError: PACKET_JOB_MISMATCH
  field: wo_no
  existing: WO-001
  current: WO-002
```

**원인:** 기존 job.json의 WO/Line과 현재 packet.xlsx가 다름 (잘못된 폴더에 파일 복사)

**해결:**
1. 올바른 job 폴더 확인
2. 옵션 A: 올바른 폴더로 packet.xlsx 이동
3. 옵션 B: 의도적 리셋이면 job.json 삭제 후 재실행
   ```bash
   # ⚠️ 주의: job_id가 새로 생성됨
   rm jobs/<folder>/job.json
   uv run python -m src.pipeline jobs/<folder>
   ```

### 2.6 ARCHIVE_FAILED

**증상:**
```
PolicyRejectError: ARCHIVE_FAILED
  operation: copy
  errno: 28
  message: No space left on device
```

**원인:** derived 사진 아카이브(trash로 이동) 실패

**해결:**
1. errno 확인:
   - `28`: 디스크 공간 부족 → 정리 필요
   - `13`: 권한 없음 → 폴더 권한 확인
   - `30`: 읽기 전용 → 파일 시스템 확인
2. 디스크 공간 확보:
   ```bash
   df -h
   du -sh jobs/*/photos/trash/
   # 오래된 trash 정리
   find jobs/*/photos/trash/ -mtime +30 -delete
   ```
3. 권한 수정:
   ```bash
   chmod -R u+w jobs/<folder>/photos/
   ```

---

## 3.5. Override Reason 품질 검증

Override는 필수 필드 누락 시 사용자가 명시적 사유를 제공하고 건너뛸 수 있는 기능입니다.
**"면책 버튼"화 방지**를 위해 품질 검증이 적용됩니다.

### Override Reason 구조

```json
{
  "reason_code": "MISSING_PHOTO",
  "reason_detail": "현장 촬영 일정 지연으로 대체 자료 사용 (추후 보완 예정)"
}
```

**필수 조건:**
- `reason_code`: `OverrideReasonCode` enum 값 (아래 참조)
- `reason_detail`: **최소 10자** 이상의 구체적 사유

### OverrideReasonCode 값

| 코드 | 의미 | 예시 상황 |
|------|------|-----------|
| `MISSING_PHOTO` | 사진 누락 | 현장 사정으로 촬영 불가 |
| `DATA_UNAVAILABLE` | 데이터 미제공 | 고객사에서 미전달 |
| `CUSTOMER_REQUEST` | 고객 요청 | 특정 정보 비공개 요청 |
| `DEVICE_FAILURE` | 장비 고장 | 측정 장비 고장으로 측정 불가 |
| `OCR_UNREADABLE` | OCR 인식 불가 | 인쇄 품질 저하로 판독 불가 |
| `FIELD_NOT_APPLICABLE` | 해당 없음 | 해당 공정에서 불필요한 필드 |
| `OTHER` | 기타 | 위 분류에 해당하지 않는 사유 |

### 금지 토큰 (자동 거절)

다음 값만으로 사유를 제출하면 **즉시 거절**됩니다:

```
"ok", "okay", "n/a", "na", "none", "-", "skip", "pass", "test",
".", "..", "...", "x", "xx", "xxx", "ㅇ", "ㅇㅇ", "ㅇㅇㅇ"
```

### 예시: 유효한 Override Reason

**예시 1: 신규 구조 (권장)**
```json
{
  "inspector": {
    "reason_code": "DATA_UNAVAILABLE",
    "reason_detail": "담당자 인사 정보 시스템 연동 전으로 수기 입력 대기"
  }
}
```

**예시 2: 레거시 문자열 형식 (하위 호환)**
```
"MISSING_PHOTO: 현장 일정 지연으로 사진 미촬영, 추후 보완 예정입니다"
```
→ 파이프라인이 자동으로 `reason_code=MISSING_PHOTO`, `reason_detail=현장 일정 지연으로...`로 파싱

**예시 3: 코드 없는 레거시 형식**
```
"고객사 보안 정책으로 해당 정보 비공개 처리"
```
→ 자동으로 `reason_code=OTHER`, `reason_detail=고객사 보안 정책으로...`로 변환

### 거절되는 경우

| 입력 | 거절 사유 |
|------|-----------|
| `"ok"` | 금지 토큰 |
| `"n/a"` | 금지 토큰 |
| `"사유 없음"` | 최소 길이 미달 (4자 < 10자) |
| `{"code": "INVALID", "detail": "..."}` | 유효하지 않은 코드 → OTHER로 처리됨 |

### 에러 코드

| 코드 | 의미 |
|------|------|
| `INVALID_OVERRIDE_REASON` | 금지 토큰 또는 최소 길이 미달 |
| `INVALID_OVERRIDE_CODE` | 유효하지 않은 reason_code (자동 OTHER 변환) |

### 로그 스키마

Override 적용 시 `run_log.overrides[]`에 기록:

```json
{
  "code": "OVERRIDE_APPLIED",
  "timestamp": "2024-01-15T09:30:00Z",
  "field_or_slot": "inspector",
  "type": "field",
  "reason_code": "DATA_UNAVAILABLE",
  "reason_detail": "담당자 인사 정보 시스템 연동 전으로 수기 입력 대기",
  "reason": "DATA_UNAVAILABLE: 담당자 인사 정보 시스템 연동 전으로 수기 입력 대기",
  "user": "admin"
}
```

### 3.6. 사진 처리 파이프라인

사진 업로드부터 최종 문서 생성까지의 전체 흐름입니다.

#### 디렉터리 구조

```
jobs/<JOB-ID>/
└── photos/
    ├── raw/           ← 업로드된 원본 사진 (01_overview.jpg)
    ├── derived/       ← 슬롯별 1개 파일 (overview.jpg)
    └── _trash/        ← 교체된 이전 파일
        └── 2024-01-15T093000-RUN-001/
            └── overview.jpg
```

#### 처리 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                        Photo Pipeline                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  POST /api/chat/upload                                           │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────┐ │
│  │ photos/raw/ │ → │ slot 자동 매칭 │ → │ intake_session.json │ │
│  │ 저장        │    │ (파일명 패턴) │    │ photo_mappings 기록 │ │
│  └─────────────┘    └──────────────┘    └─────────────────────┘ │
│                                                                  │
│  POST /api/generate                                              │
│       │                                                          │
│       ▼                                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PhotoService.validate_and_process()                       │   │
│  │                                                           │   │
│  │  1. raw/ 스캔 → 슬롯 매핑                                 │   │
│  │  2. 중복 시 prefer_order 선택 (.jpg > .jpeg > .png)       │   │
│  │  3. 기존 derived/ → _trash/ 아카이브                      │   │
│  │  4. 새 파일 → derived/ 복사                               │   │
│  │  5. 필수 슬롯 검증 (fail-fast / override)                 │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│       ▼                                                          │
│  ┌─────────────────┐                                             │
│  │ run_log.json    │                                             │
│  │ photo_processing│ ← 모든 처리 내역 기록                       │
│  └─────────────────┘                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 슬롯 정의 (definition.yaml)

```yaml
photos:
  allowed_extensions: [".jpg", ".jpeg", ".png"]
  prefer_order: [".jpg", ".jpeg", ".png"]  # 중복 시 우선순위
  slots:
    - key: overview
      basename: "01_overview"
      required: true
      override_allowed: false
      description: "제품 전체 사진"
    - key: label_serial
      basename: "02_label_serial"
      required: true
      override_allowed: false
    - key: measurement_setup
      basename: "03_measurement_setup"
      required: true
      override_allowed: true
      override_requires_reason: true
    - key: defect
      basename: "04_defect"
      required: false
      override_allowed: true
```

#### API 파라미터

**POST /api/generate** 확장:

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `photo_overrides` | JSON string | 사진 슬롯 override (슬롯 키 → 사유) |

**예시:**
```bash
curl -X POST /api/generate \
  -F "session_id=..." \
  -F 'photo_overrides={"measurement_setup": "DEVICE_FAILURE: 측정 장비 고장으로 촬영 불가"}'
```

#### 에러 코드

| 코드 | 의미 | 조치 |
|------|------|------|
| `PHOTO_REQUIRED_MISSING` | 필수 슬롯 사진 없음 (override 불가) | 사진 업로드 필요 |
| `PHOTO_OVERRIDE_REQUIRED` | 필수 슬롯 사진 없음 (override 가능) | 사진 또는 override 사유 제공 |

#### photo_processing 로그 스키마

```json
{
  "photo_processing": [
    {
      "slot_id": "overview",
      "action": "mapped",
      "raw_path": "photos/raw/01_overview.jpg",
      "derived_path": "photos/derived/overview.jpg",
      "timestamp": "2024-01-15T09:30:00Z"
    },
    {
      "slot_id": "label_serial",
      "action": "archived",
      "raw_path": "photos/raw/02_label_serial.jpg",
      "derived_path": "photos/derived/label_serial.jpg",
      "archived_path": "photos/_trash/2024-01-15T093000-RUN-001/label_serial.jpg",
      "timestamp": "2024-01-15T09:30:00Z"
    },
    {
      "slot_id": "measurement_setup",
      "action": "override",
      "override_reason": "DEVICE_FAILURE: 측정 장비 고장",
      "timestamp": "2024-01-15T09:30:00Z"
    }
  ]
}
```

#### action 종류

| action | 의미 |
|--------|------|
| `mapped` | raw → derived 정상 복사 |
| `archived` | 기존 derived → _trash 이동 후 새 파일 복사 |
| `override` | 필수 슬롯 누락, override 사유로 통과 |
| `missing` | 필수 슬롯 누락, override 불가 (실패 원인) |
| `skipped` | 선택 슬롯 누락 (정상) |

#### 테스트 케이스 커버리지

| TC | 시나리오 | 검증 사항 |
|----|----------|-----------|
| TC1 | 정상 매핑 | raw 저장 → slot 매칭 → derived 생성 |
| TC2 | derived 교체 | 기존 파일 → _trash 아카이브 |
| TC3 | 필수 슬롯 누락 (fail-fast) | override_allowed=false → 즉시 에러 |
| TC4 | 필수 슬롯 누락 (override) | 유효한 사유 → 통과 |
| TC5 | 중복 사진 | prefer_order 기준 선택 |
| TC6 | run log 기록 | photo_processing 배열 검증 |

---

### 3.7. 사진 슬롯 매칭 신뢰도

사진 파일이 올바른 슬롯에 매칭되었는지 확인하는 신뢰도 시스템입니다.

#### 신뢰도 레벨

| 레벨 | 조건 | 동작 |
|------|------|------|
| `HIGH` | basename 정확히 일치 + OCR 키워드 검증 | 자동 매핑 |
| `MEDIUM` | basename 접두사 일치 | 자동 매핑 |
| `LOW` | key 접두사만 일치 | ⚠️ 사용자 확인 필요 |
| `AMBIGUOUS` | 여러 슬롯에 매칭 가능 | ⚠️ 사용자 확인 필요 |

#### 매칭 우선순위

```
1. basename_exact: "02_label_serial.jpg" → label_serial (HIGH)
2. basename_prefix: "02_label_serial_v2.jpg" → label_serial (MEDIUM)
3. key_prefix: "label_serial_test.jpg" → label_serial (LOW)
```

#### OCR 검증 (label_serial 슬롯)

`label_serial` 슬롯은 OCR 키워드 검증이 적용됩니다:
- 검증 키워드: `S/N`, `Serial`, `시리얼`, `Model`, `모델`, `LOT`
- 키워드 발견 시: `MEDIUM` → `HIGH`로 승격
- 사진에서 라벨/시리얼 정보가 확인되어야 신뢰도 높음

#### 신뢰도별 운영자 대응

| 신뢰도 | 필요 조치 |
|--------|-----------|
| HIGH/MEDIUM | 조치 불필요 (자동 매핑됨) |
| LOW | 파일명 수정 권장 (예: `serial.jpg` → `02_label_serial.jpg`) |
| AMBIGUOUS | 중복 파일 정리 필요 |

#### 로그 확인

```bash
# 슬롯 매핑 결과 확인
cat jobs/<folder>/logs/run_*.json | jq '.photo_processing[] | {slot_id, action, confidence}'

# LOW 신뢰도 매핑 찾기
grep -r '"confidence":"low"' jobs/*/logs/
```

---

### 3.8. _trash 보관 정책 및 Purge

`photos/_trash/` 폴더의 아카이브 파일 관리 정책입니다.

#### 정책 설정 (definition.yaml)

```yaml
photos:
  trash_retention:
    retention_days: 30        # 30일 경과 후 purge 대상
    max_size_per_job_mb: 100  # job당 최대 100MB
    max_total_size_gb: 10     # 전체 최대 10GB
    purge_mode: compress      # delete | compress | external
    archive_dir: "_archive"   # 압축 파일 저장 위치
    min_keep_count: 3         # 최소 3개 RUN은 유지
```

#### Purge 모드

| 모드 | 동작 |
|------|------|
| `delete` | 완전 삭제 (복구 불가) |
| `compress` | tar.gz로 압축 후 `_archive/`로 이동 |
| `external` | 외부 스토리지로 이동 (미구현) |

#### Purge 스크립트 실행

```bash
# Dry-run (기본값) - 삭제될 항목 미리 확인
uv run python scripts/purge_trash.py --jobs-root jobs/

# 특정 job만 확인
uv run python scripts/purge_trash.py --job jobs/JOB-001

# 실제 삭제 실행
uv run python scripts/purge_trash.py --jobs-root jobs/ --execute

# 커스텀 definition.yaml 사용
uv run python scripts/purge_trash.py --definition custom_def.yaml --execute
```

#### 자동화 (cron 설정)

```bash
# /etc/cron.daily/purge-photo-trash
#!/bin/bash
cd /path/to/project
uv run python scripts/purge_trash.py --jobs-root jobs/ --execute >> /var/log/purge_trash.log 2>&1
```

#### Purge 결과 확인

```bash
# 삭제된 RUN 목록 확인
ls jobs/<folder>/photos/_archive/

# 압축 파일 내용 확인
tar -tzvf jobs/<folder>/photos/_archive/20241215_093000_RUN-001.tar.gz

# 현재 _trash 용량 확인
du -sh jobs/*/photos/_trash/
```

#### 주의사항

- `min_keep_count`로 최소 N개 RUN은 항상 유지됩니다
- `compress` 모드 사용 시 원본은 삭제되고 압축본만 남습니다
- 복구가 필요한 경우 `_archive/` 폴더의 tar.gz 파일 사용

---

### 3.9. Generate 동시성 보호

동일 job에 대해 동시에 generate가 호출되면 충돌을 방지합니다.

#### 동작 방식

```
┌──────────────────────────────────────────────────────────────┐
│                    Generate 동시성 보호                       │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Request A (09:30:00)     Request B (09:30:01)               │
│       │                        │                              │
│       ▼                        ▼                              │
│  ┌─────────┐              ┌─────────┐                        │
│  │ 락 획득 │ ← 성공       │ 락 대기 │ ← 재시도 중            │
│  │ (.lock) │              │         │                        │
│  └─────────┘              └─────────┘                        │
│       │                        │                              │
│       ▼                        │                              │
│  Generate 작업               (대기)                           │
│       │                        │                              │
│       ▼                        ▼                              │
│  ┌─────────┐              ┌─────────┐                        │
│  │ 락 해제 │              │ 락 획득 │ ← 대기 후 성공         │
│  └─────────┘              └─────────┘                        │
│       │                        │                              │
│       ▼                        ▼                              │
│  Response A               Generate 작업                       │
│  (성공)                        │                              │
│                                ▼                              │
│                           Response B                          │
│                           (성공)                              │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

#### 에러 코드

| 코드 | HTTP | 의미 |
|------|------|------|
| `JOB_JSON_LOCK_TIMEOUT` | 409 Conflict | 락 획득 타임아웃 |

#### 타임아웃 설정

```yaml
# configs/production.yaml
pipeline:
  lock_retry_interval: 0.05  # 재시도 간격 (초)
  lock_max_retries: 40       # 최대 재시도 횟수 (0.05 × 40 = 2초)
```

#### 운영자 대응

**409 Conflict 발생 시:**

```bash
# 1. 다른 generate 프로세스 확인
ps aux | grep "generate"

# 2. 락 디렉터리 확인
ls -la jobs/<folder>/.lock/

# 3. 프로세스가 없는데 락이 있다면 (stale lock)
rmdir jobs/<folder>/.lock/

# 4. 재시도
curl -X POST /api/generate ...
```

**동시 호출이 필요한 경우:**
- 서로 다른 job 폴더 사용 (병렬 처리 가능)
- 동일 job은 순차 처리만 지원

#### 로그 확인

```bash
# 락 타임아웃 로그 확인
cat jobs/<folder>/logs/run_*.json | jq 'select(.reject_reason == "JOB_JSON_LOCK_TIMEOUT")'

# 동시 접근 시도 확인
grep -r "JOB_JSON_LOCK_TIMEOUT" jobs/*/logs/
```

---

### 3.10. AI Raw 데이터 저장 정책

AI 호출의 **조건부 재현성(Conditional Reproducibility)** 확보를 위해 메타데이터와 원본 데이터를 저장합니다.

> ⚠️ **주의**: LLM은 동일 입력에도 약간 다른 결과를 반환할 수 있습니다.
> 저장된 메타데이터는 "유사한 결과"를 기대할 수 있게 하지만, **완전한 재현**은 보장하지 않습니다.

#### 저장 목적

- **조건부 재현성**: 동일 파라미터로 유사한 결과를 기대할 수 있음
- **원인 추적**: 분쟁/감사 시 "왜 이런 결과가 나왔는지" 추적 가능
- **디버깅**: 파싱 실패 시에도 원본 응답 확인 가능

#### 저장 항목

##### 조건부 재현성 메타데이터 (필수)

| 항목 | 필드 | 설명 |
|------|------|------|
| **Provider** | `provider` | 사용된 제공자 (`anthropic`, `regex`) |
| **모델** | `model_requested`, `model_used` | 요청/실제 사용 모델 |
| **호출 파라미터** | `model_params` | `{temperature, top_p, max_tokens}` 등 |
| **요청 ID** | `request_id` | API 응답의 request ID (가능한 경우) |
| **프롬프트 해시** | `prompt_hash` | 프롬프트 SHA-256 해시 (검색/중복 제거용) |
| **추출 방법** | `extraction_method` | `llm` 또는 `regex` |
| **추출 시각** | `extracted_at` | ISO 8601 타임스탬프 |

##### Raw 저장 (storage_level에 따라)

| 항목 | 필드 | 설명 |
|------|------|------|
| **LLM 원본 응답** | `llm_raw_output` | API 응답 전체 (파싱 전 원문) |
| **응답 해시** | `llm_raw_output_hash` | 응답 SHA-256 해시 |
| **Truncation 여부** | `llm_raw_truncated` | 크기 제한으로 잘렸는지 여부 |

##### 프롬프트 분리 저장 (보안)

| 항목 | 필드 | 설명 |
|------|------|------|
| **템플릿 ID** | `prompt_template_id` | 사용된 프롬프트 템플릿 경로 |
| **템플릿 버전** | `prompt_template_version` | 템플릿 버전 |
| **유저 변수** | `prompt_user_variables` | `{user_input, ocr_text}` (분리 저장) |
| **렌더링된 프롬프트** | `prompt_rendered` | 전체 프롬프트 (FULL 모드) |

##### 정규식 추출용

| 항목 | 필드 | 설명 |
|------|------|------|
| **정규식 버전** | `regex_version` | `"1.0.0:abc123def456"` (버전:해시) |

#### 저장 레벨 (RawStorageLevel)

```python
class RawStorageLevel(str, Enum):
    NONE = "none"      # 저장 안 함
    MINIMAL = "minimal"  # 해시만 저장 (용량 절약)
    FULL = "full"       # 원문 저장 (재현성 최대, 기본값)
```

| 레벨 | llm_raw_output | llm_raw_output_hash | prompt_rendered |
|------|----------------|---------------------|-----------------|
| NONE | ✗ | ✗ | ✗ |
| MINIMAL | ✗ | ✓ | ✗ |
| FULL | ✓ (truncation 적용) | ✓ | ✓ |

#### 저장 위치

```
jobs/<JOB-ID>/
└── inputs/
    └── intake_session.json    ← AI raw 데이터 포함
        {
          "extraction_result": {
            "success": true,
            "fields": {...},

            // 조건부 재현성 메타데이터
            "provider": "anthropic",
            "model_requested": "claude-opus-4-5-20251101",
            "model_used": "claude-opus-4-5-20251101",
            "model_params": {"max_tokens": 4096, "temperature": 0.5},
            "request_id": "msg_abc123...",
            "extraction_method": "llm",
            "extracted_at": "2024-01-15T09:30:00Z",

            // Raw 저장
            "llm_raw_output": "...",
            "llm_raw_output_hash": "sha256:abc123...",
            "llm_raw_truncated": false,

            // 프롬프트 분리
            "prompt_template_id": "prompts/extract_fields.txt",
            "prompt_template_version": "1.0.0",
            "prompt_user_variables": {"user_input": "...", "ocr_text": "..."},
            "prompt_rendered": "...",
            "prompt_hash": "sha256:def456..."
          }
        }
```

#### 보안 정책

| 항목 | 정책 |
|------|------|
| **저장 위치** | `intake_session.json`에만 저장 |
| **RunLog 분리** | `run_log.json`에는 raw 미포함 (메타데이터만) |
| **프롬프트 분리** | 템플릿과 유저 입력을 분리하여 보안 리스크 감소 |
| **크기 제한** | `max_raw_size` (기본 1MB) 초과 시 truncation |
| **보관 기간** | job 폴더 생명주기와 동일 |
| **PII 마스킹** | `AIRawStorageConfig.mask_pii=True`로 활성화 가능 |

#### 저장 시점

```
[추출 요청]
     │
     ▼
AnthropicProvider.extract_fields()
├── prompt = _build_prompt(...)         ← 프롬프트 구성
├── prompt_hash = compute_hash(prompt)  ← 해시 계산
├── model_params = _collect_model_params()  ← 파라미터 수집
├── response = _call_api(prompt)        ← API 호출
├── request_id = response.id            ← 요청 ID 추출
└── _apply_raw_storage(...)             ← storage_level에 따라 저장
     │
     ▼
IntakeService.add_extraction_result()
     │
     ▼
intake_session.json 저장
```

#### 정규식 추출 시

필수 필드가 정규식으로 모두 추출 가능하면 LLM 호출을 스킵합니다:

```json
{
  "provider": "regex",
  "model_requested": "regex",
  "model_used": "regex",
  "extraction_method": "regex",
  "regex_version": "1.0.0:abc123def456",
  "llm_raw_output": null,
  "prompt_used": null
}
```

#### 로그 확인

```bash
# 조건부 재현성 메타데이터 확인
cat jobs/<folder>/inputs/intake_session.json | jq '.extraction_result | {
  provider,
  model_used,
  model_params,
  request_id,
  prompt_hash,
  extraction_method
}'

# raw 데이터 확인
cat jobs/<folder>/inputs/intake_session.json | jq '.extraction_result.llm_raw_output'

# run_log에는 raw 없음 확인
cat jobs/<folder>/logs/run_*.json | jq 'keys'
# → ["job_id", "run_id", "result", ...] (llm_raw_output 없음)
```

#### 재현 절차

분쟁/감사 시 AI 호출 재현 (유사 결과 기대):

```bash
# 1. 조건부 재현성 정보 확인
cat jobs/<folder>/inputs/intake_session.json | jq '{
  provider: .extraction_result.provider,
  model: .extraction_result.model_used,
  params: .extraction_result.model_params,
  prompt_hash: .extraction_result.prompt_hash,
  request_id: .extraction_result.request_id
}'

# 2. 동일 파라미터로 재호출 (유사 결과 기대)
# model_params와 prompt_rendered를 사용하여 API 재호출
# 주의: 완전히 동일한 결과는 보장되지 않음 (LLM 특성)
```

#### 주의사항

- **조건부 재현성**: 완전한 재현은 불가능, 유사한 결과만 기대 가능
- **파싱 실패해도 저장**: `success=false`여도 `llm_raw_output`은 저장됨
- **용량 제한**: `max_raw_size` 초과 시 truncation (기본 1MB)
- **보안 주의**: `intake_session.json`에 원본 데이터가 있으므로 접근 권한 관리 필요

---

### 3.11. 골든 테스트 정책

DOCX/XLSX 렌더링 결과의 **의미적 비교**를 통한 회귀 테스트 체계입니다.

> ⚠️ **바이너리 비교 불가**: DOCX/XLSX는 타임스탬프, UUID 등 가변 메타데이터를 포함하므로
> 바이트 단위 비교는 항상 실패합니다. 대신 **의미적 내용**만 비교합니다.

#### 골든 테스트 철학

| 원칙 | 설명 |
|------|------|
| **의미 비교** | 바이트가 아닌 텍스트, 테이블, 셀 값 비교 |
| **정규화** | 타임스탬프 → `<TS>`, UUID → `<UUID>`, 공백 축소 |
| **콘텐츠 변경만 실패** | 서식 변경은 통과, 내용 변경만 감지 |
| **사람이 읽기 쉬운 diff** | 실패 시 어떤 값이 달라졌는지 명확히 표시 |

#### 디렉터리 구조

```
tests/golden/
├── test_golden.py           # pytest 테스트 파일
├── __init__.py
└── scenario_001_basic/      # 시나리오 폴더
    ├── input_packet.json    # 렌더링 입력 데이터
    ├── overrides.json       # 필드 override (선택)
    ├── photos/              # 테스트용 사진
    │   ├── overview.jpg
    │   └── label_serial.jpg
    └── expected/            # 기대 결과 (자동 생성)
        ├── docx.json        # DOCX 의미 구조
        └── xlsx.json        # XLSX 의미 구조

src/testing/golden/
├── __init__.py
├── normalize.py             # 정규화 로직
├── docx_extract.py          # DOCX → JSON 추출
├── xlsx_extract.py          # XLSX → JSON 추출
├── compare.py               # 구조 비교 유틸리티
├── runner.py                # 골든 테스트 실행기
└── generate_expected.py     # expected 파일 생성 스크립트
```

#### 정규화 규칙

| 항목 | 변환 | 예시 |
|------|------|------|
| **타임스탬프** | `<TS>` | `2024-01-15T09:30:00Z` → `<TS>` |
| **UUID** | `<UUID>` | `550e8400-e29b-41d4-...` → `<UUID>` |
| **연속 공백** | 단일 공백 | `Hello   World` → `Hello World` |
| **숫자 정밀도** | 문자열 통일 | `1.0`, `1.00` → `"1.0"` |

#### 테스트 실행

```bash
# 전체 골든 테스트 실행
uv run pytest tests/golden/test_golden.py -v

# 특정 시나리오만
uv run pytest tests/golden/test_golden.py -k "scenario_001" -v

# 상세 출력 (실패 시 diff 확인)
uv run pytest tests/golden/test_golden.py -v --tb=long
```

#### Expected 파일 생성

> ⚠️ **CI에서 절대 실행 금지**: 수동 검토 후에만 커밋하세요.

```bash
# 모든 시나리오 목록 확인
python -m src.testing.golden.generate_expected --list

# 특정 시나리오 생성
python -m src.testing.golden.generate_expected scenario_001_basic

# 기존 파일 덮어쓰기 (주의!)
python -m src.testing.golden.generate_expected scenario_001_basic --force
```

**생성 후 필수 검토:**
1. `expected/docx.json` 내용 확인
2. `expected/xlsx.json` 측정값, 셀 값 확인
3. 정상이면 커밋, 비정상이면 입력 데이터 수정

#### 새 시나리오 추가

```bash
# 1. 시나리오 폴더 생성
mkdir -p tests/golden/scenario_002_edge_case

# 2. 입력 파일 작성
# tests/golden/scenario_002_edge_case/input_packet.json
{
  "wo_no": "WO-2024-002",
  "line": "L2",
  "part_no": "PART-B200",
  "lot": "LOT-20240116",
  "result": "FAIL",
  ...
}

# 3. expected 생성
python -m src.testing.golden.generate_expected scenario_002_edge_case

# 4. 생성된 expected 검토 후 커밋
git add tests/golden/scenario_002_edge_case/
git commit -m "Add golden scenario: edge case for FAIL result"
```

#### 테스트 실패 대응

**실패 시 출력 예시:**
```
AssertionError: Golden test mismatch (3 differences)

=== Golden Comparison Report ===

[1] Path: paragraphs[0]
    Expected: "Work Order: WO-2024-001"
    Actual:   "Work Order: WO-2024-999"

[2] Path: tables[0][1][2]
    Expected: "10.02"
    Actual:   "10.05"
```

**대응 절차:**

| 상황 | 조치 |
|------|------|
| **의도한 변경** | `--force`로 expected 재생성 후 검토/커밋 |
| **버그 발생** | 렌더링 코드 수정 |
| **테스트 데이터 오류** | `input_packet.json` 수정 |

#### 추출 내용

**DOCX 추출 (`docx.json`):**
```json
{
  "paragraphs": ["Work Order: WO-2024-001", "Line: L1", ...],
  "tables": [
    [["항목", "규격", "측정값"], ["외경", "10.0 ± 0.1", "10.02"]],
    ...
  ],
  "images": [
    {"rel_id": "rId7", "filename": "image1.jpeg", "size": 12345}
  ],
  "metadata": {...}
}
```

**XLSX 추출 (`xlsx.json`):**
```json
{
  "sheets": ["Sheet1"],
  "cells": {
    "A1": "WO-2024-001",
    "B1": "L1"
  },
  "measurements": [
    {"item": "외경", "spec": "10.0 ± 0.1", "measured": "10.02", "result": "PASS"}
  ],
  "metadata": {...}
}
```

#### CI 통합

```yaml
# .github/workflows/test.yml
- name: Run Golden Tests
  run: uv run pytest tests/golden/ -v --tb=short
```

**CI에서 실패하면:**
1. 로컬에서 동일 테스트 실행하여 diff 확인
2. 의도한 변경인지 판단
3. 의도한 변경이면 expected 재생성 후 PR 업데이트

#### 과도한 정규화 방지

Normalizer는 치환 횟수를 추적하여 과도한 정규화를 감지합니다:

```python
from src.testing.golden import Normalizer

normalizer = Normalizer(uuid_threshold=20, timestamp_threshold=20)
normalizer.normalize(document_content)

# 치환 통계 확인
print(normalizer.stats.to_dict())
# {'UUID': 3, 'TS': 1, 'DATE': 2, 'total': 6}

# 임계값 초과 경고 확인
warnings = normalizer.check_thresholds()
if warnings:
    print("WARNING:", warnings)
```

**임계값 기본값:**
| 항목 | 기본값 | 의미 |
|------|--------|------|
| UUID | 20 | UUID가 20개 이상이면 경고 |
| Timestamp | 20 | 타임스탬프가 20개 이상이면 경고 |
| Date | 50 | 날짜가 50개 이상이면 경고 |

#### XLSX 헤더 기반 추출

컬럼 위치 변경에 강건한 헤더 기반 측정 데이터 추출:

```python
# 고정 컬럼 방식 (기존)
measurement_config = {
    "sheet": "Sheet1",
    "start_row": 5,
    "columns": {"item": "A", "spec": "B", "measured": "C"}
}

# 헤더 기반 방식 (권장 - 컬럼 이동에 강건)
measurement_config = {
    "sheet": "Sheet1",
    "header_row": 4,
    "headers": {
        "item": "항목",
        "spec": "규격",
        "measured": "측정값",
        "result": "판정"
    }
}
```

#### CI 가드

`generate_expected.py`는 CI 환경에서 실행을 차단합니다:

```bash
# CI에서 실행 시
$ CI=true python -m src.testing.golden.generate_expected
ERROR: generate_expected cannot run in CI environment.
Detected CI indicator: CI=true
```

감지되는 CI 환경변수:
- `CI`, `GITHUB_ACTIONS`, `GITLAB_CI`, `JENKINS_URL`, `CIRCLECI`, `TRAVIS`, `BUILDKITE`, `TF_BUILD`, `CODEBUILD_BUILD_ID`

#### 이미지 골든 테스트

`scenario_002_with_photos`는 사진 파이프라인을 검증합니다:

```json
// expected/docx.json 예시
{
  "images": [
    {
      "rel_id": "rId9",
      "filename": "image1.jpg",
      "size_bytes": 170,
      "inferred_slot": null,
      "_image_summary": {
        "total_count": 2,
        "relationship_count": 2,
        "media_file_count": 2
      }
    },
    ...
  ]
}
```

**검증 항목:**
- `total_count`: 삽입된 이미지 총 개수
- `media_file_count`: `word/media/` 폴더 내 파일 수
- `inferred_slot`: 파일명에서 추론된 슬롯 (overview, label_serial 등)

#### 주의사항

- **expected 파일은 수동 검토 필수**: 자동 생성 후 반드시 내용 확인
- **CI에서 generate_expected 금지**: 코드로 차단됨 (CI 환경변수 감지)
- **사진 플레이스홀더**: 템플릿에 `{{photo_overview}}` 등이 있어야 이미지 삽입
- **시나리오 독립성**: 각 시나리오는 독립적으로 실행 가능해야 함
- **정규화 임계값**: 치환이 너무 많으면 문서 이상 의심

---

## 4. 경고 대응

경고는 파이프라인을 중단하지 않지만, 로그에 기록됩니다.

### 경고 코드 Quick Reference

| 코드 | 의미 | 조치 필요 |
|------|------|-----------|
| `PHOTO_DUPLICATE_AUTO_SELECTED` | 슬롯에 여러 파일, 자동 선택 | ⚠️ 확인 권장 |
| `PHOTO_LOW_CONFIDENCE_MATCH` | 슬롯 매칭 신뢰도 낮음 | ⚠️ 파일명 확인 권장 |
| `PHOTO_AMBIGUOUS_MATCH` | 여러 슬롯에 매칭 가능 | ⚠️ 파일 정리 필요 |
| `PARSE_ERROR_REFERENCE` | 참조 필드 파싱 실패 → null | ℹ️ 정보 |
| `PHOTO_OPTIONAL_MISSING` | 선택 사진 누락 | ℹ️ 정보 |
| `FSYNC_FAILED` | 파일 동기화 실패 | ⚠️ 확인 권장 |

### 3.1 PHOTO_DUPLICATE_AUTO_SELECTED

**로그 예시:**
```json
{
  "code": "PHOTO_DUPLICATE_AUTO_SELECTED",
  "field_or_slot": "overview",
  "original_value": "01_overview.jpg, 01_overview.png",
  "resolved_value": "01_overview.jpg"
}
```

**의미:** 같은 슬롯에 여러 파일이 있어 우선순위(jpg > jpeg > png)로 선택됨

**조치:**
1. 의도한 파일이 선택되었는지 확인
2. 불필요한 파일 제거 (선택사항)

### 3.2 FSYNC_FAILED

**로그 예시:**
```json
{
  "code": "FSYNC_FAILED",
  "field_or_slot": "01_overview",
  "message": "fsync failed: [Errno 22], data preserved"
}
```

**의미:** 파일 동기화(fsync) 실패 (NFS, 네트워크 드라이브 등에서 발생 가능)

**조치:**
1. 파일 복사 자체는 완료됨 (대부분의 경우 문제없음)
2. **단, 내구성(durability) 보장 불가** - 시스템 크래시 시 데이터 유실 가능성 있음
3. 반복 발생 시 스토리지 상태 점검 필수
4. 네트워크 드라이브 사용 중이라면 로컬 스토리지 전환 검토

> ⚠️ 프로덕션 환경에서 반복 발생 시 스토리지 인프라 점검 권장

---

## 5. 락 문제 해결

### 5.1 락 구조

```
jobs/<folder>/
└── .job_json.lock/    ← 디렉터리 락 (존재 = 잠김)
```

**정상 상태:** `.job_json.lock/` 디렉터리가 없음

### 5.2 JOB_JSON_LOCK_TIMEOUT 대응

**증상:**
```
PolicyRejectError: JOB_JSON_LOCK_TIMEOUT
  job_dir: jobs/demo_001
  attempts: 40
  total_wait: 2.0
```

**원인 진단:**
```bash
# 1. 락 디렉터리 존재 확인
ls -la jobs/<folder>/.job_json.lock/

# 2. 다른 파이프라인 프로세스 확인
ps aux | grep "pipeline"

# 3. 락 생성 시간 확인
stat jobs/<folder>/.job_json.lock/
```

**해결 방법:**

| 상황 | 조치 |
|------|------|
| 다른 프로세스 실행 중 | 완료 대기 또는 종료 |
| 프로세스 없음 (stale lock) | 수동 삭제 |
| 프로세스 크래시 | 수동 삭제 |

### 5.3 Stale Lock 수동 삭제

```bash
# 1. 다른 프로세스가 없는지 확인
ps aux | grep "pipeline"

# 2. 락 디렉터리 삭제
rmdir jobs/<folder>/.job_json.lock

# 3. 파일이 있는 경우 (비정상)
rm -rf jobs/<folder>/.job_json.lock

# 4. 파이프라인 재실행
uv run python -m src.pipeline jobs/<folder>
```

> ⚠️ **주의:** 다른 프로세스가 실행 중일 때 삭제하면 데이터 손상 가능

### 5.4 락 timeout 조정

프로덕션 환경에서 timeout 증가가 필요한 경우:

```yaml
# configs/production.yaml
pipeline:
  lock_timeout_seconds: 5    # 기본 2초 → 5초
  lock_max_retries: 100      # 기본 40 → 100
```

---

## 6. 백업 및 복구

### 6.1 백업 대상

| 우선순위 | 대상 | 경로 | 복구 가능성 |
|----------|------|------|-------------|
| 🔴 필수 | packet.xlsx | `jobs/<folder>/packet.xlsx` | 원본 유실 시 복구 불가 |
| 🔴 필수 | 사진 원본 | `jobs/<folder>/photos/raw/` | 원본 유실 시 복구 불가 |
| 🟡 권장 | job.json | `jobs/<folder>/job.json` | 재생성 가능 (job_id 변경) |
| 🟢 선택 | 로그 | `jobs/<folder>/logs/` | 감사용, 재생성 불가 |
| 🟢 선택 | deliverables | `jobs/<folder>/deliverables/` | 재생성 가능 |

### 6.2 백업 스크립트

```bash
#!/bin/bash
# backup_job.sh

JOB_DIR=$1
BACKUP_DIR="/backup/jobs/$(date +%Y%m%d)"

mkdir -p "$BACKUP_DIR"

# 필수 파일 백업
tar -czvf "$BACKUP_DIR/$(basename $JOB_DIR).tar.gz" \
    -C "$(dirname $JOB_DIR)" \
    "$(basename $JOB_DIR)/packet.xlsx" \
    "$(basename $JOB_DIR)/photos/raw/" \
    "$(basename $JOB_DIR)/job.json" \
    "$(basename $JOB_DIR)/logs/"

echo "Backup complete: $BACKUP_DIR/$(basename $JOB_DIR).tar.gz"
```

### 6.3 복구 절차

**전체 복구:**
```bash
# 백업에서 복원
tar -xzvf /backup/jobs/20240115/demo_001.tar.gz -C jobs/

# 파이프라인 재실행 (deliverables 재생성)
uv run python -m src.pipeline jobs/demo_001 --rebuild-derived
```

**job.json 유실 시:**
```bash
# ⚠️ 새 job_id 생성됨
rm jobs/<folder>/job.json  # 이미 없으면 생략
uv run python -m src.pipeline jobs/<folder>
```

> ⚠️ job_id 변경 시 기존 로그와의 연결이 끊어짐

### 6.4 일괄 백업 (cron)

```bash
# /etc/cron.daily/backup-jobs
#!/bin/bash
JOBS_ROOT="/path/to/jobs"
BACKUP_ROOT="/backup/jobs/$(date +%Y%m%d)"

mkdir -p "$BACKUP_ROOT"

for job in "$JOBS_ROOT"/*/; do
    if [ -f "$job/packet.xlsx" ]; then
        job_name=$(basename "$job")
        tar -czvf "$BACKUP_ROOT/$job_name.tar.gz" \
            -C "$JOBS_ROOT" \
            "$job_name/packet.xlsx" \
            "$job_name/photos/raw/" \
            "$job_name/job.json" 2>/dev/null
    fi
done

# 30일 이상 백업 삭제 (날짜별 디렉터리만 대상)
find /backup/jobs/ -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
```

---

## 7. 긴급 대응

### 7.1 연락처

| 역할 | 담당자 | 연락처 |
|------|--------|--------|
| 1차 대응 | (이름) | (연락처) |
| 2차 대응 | (이름) | (연락처) |
| 시스템 관리자 | (이름) | (연락처) |

### 7.2 긴급 상황 분류

| 등급 | 상황 | 대응 시간 |
|------|------|-----------|
| P1 | 전체 파이프라인 중단 | 1시간 이내 |
| P2 | 특정 job 처리 불가 | 4시간 이내 |
| P3 | 경고 다수 발생 | 24시간 이내 |

### 7.3 P1: 전체 파이프라인 중단

**증상:**
- 모든 job에서 동일 에러 발생
- 시스템 자원 고갈 (디스크, 메모리)

**진단:**
```bash
# 시스템 상태
df -h              # 디스크
free -h            # 메모리
ps aux | head -20  # 프로세스

# Python/의존성 확인
uv run python --version
uv run python -c "import openpyxl; import jinja2; print('OK')"
```

**대응:**
1. 즉시 담당자 연락
2. 최근 변경사항 확인 (배포, 설정 변경)
3. 시스템 자원 확보 (디스크 정리, 프로세스 종료)
4. 필요 시 이전 버전으로 롤백

### 7.4 P2: 특정 job 처리 불가

**진단:**
```bash
# 해당 job 상태 확인
ls -la jobs/<folder>/
cat jobs/<folder>/logs/run_*.json | tail -1 | jq '.'

# 다른 job 테스트 (서버 실행)
uv run uvicorn src.app.main:app --reload
```

**대응:**
1. 에러 코드 확인 → [에러 대응](#2-에러-대응) 참조
2. 입력 파일 검증 (packet.xlsx, photos)
3. job 폴더 권한 확인
4. 필요 시 job 폴더 재생성

### 7.5 롤백 절차

```bash
# 1. 현재 버전 확인
git log --oneline -5

# 2. 이전 버전으로 롤백
git checkout <previous_commit>

# 3. 의존성 재설치
uv sync --all-extras

# 4. 테스트
uv run pytest tests/
```

---

## 8. 트러블슈팅

### 8.1 웹 서버 문제

#### 서버가 시작되지 않음

**증상:**
```
Error: Address already in use
```

**해결:**
```bash
# 포트 사용 확인
lsof -i :8000

# 프로세스 종료
kill -9 <PID>

# 다른 포트로 시작
uv run uvicorn src.app.main:app --port 8001
```

#### 정적 파일이 로드되지 않음

**증상:**
- CSS/JS 404 에러
- 스타일 적용 안 됨

**해결:**
```bash
# static 폴더 확인
ls -la src/app/static/

# 권한 확인
chmod -R 755 src/app/static/
```

### 8.2 AI Provider 문제

#### API 키 오류

**증상:**
```
AuthenticationError: Invalid API key
```

**해결:**
```bash
# 환경 변수 확인
echo $MY_ANTHROPIC_KEY
echo $GOOGLE_API_KEY

# .env 파일 확인
cat .env

# 환경 변수 설정
export MY_ANTHROPIC_KEY="your-key-here"
export GOOGLE_API_KEY="your-key-here"
```

#### Rate Limit 초과

**증상:**
```
RateLimitError: Rate limit exceeded
```

**해결:**
1. 잠시 대기 후 재시도
2. `config.yaml`에서 요청 간격 설정:
```yaml
ai:
  llm:
    rate_limit_delay: 1.0  # 초
    max_retries: 3
```

### 8.3 데이터베이스/파일 문제

#### IntakeSession 로드 실패

**증상:**
```
FileNotFoundError: intake_session.json
```

**해결:**
```bash
# 세션 파일 존재 확인
ls -la jobs/<job_id>/intake_session.json

# 새 세션 생성
# (API를 통해 새 채팅 시작)
```

#### job.json 손상

**증상:**
```
JSONDecodeError: Expecting value
```

**해결:**
```bash
# 백업 확인
ls -la jobs/<job_id>/.job_json.backup

# 백업에서 복구
cp jobs/<job_id>/.job_json.backup jobs/<job_id>/job.json

# 또는 재생성 (새 job_id 발급)
rm jobs/<job_id>/job.json
# 파이프라인 재실행
```

### 8.4 템플릿 문제

#### 플레이스홀더 미치환

**증상:**
- 문서에 `{{field_name}}` 그대로 출력

**원인:**
1. 필드명 불일치
2. definition.yaml 미정의

**해결:**
```bash
# definition.yaml 확인
grep "field_name" definition.yaml

# 템플릿 플레이스홀더 확인
unzip -p templates/base/template.docx word/document.xml | grep -o '{{[^}]*}}'
```

#### Excel Named Range 오류

**증상:**
```
KeyError: 'FIELD_NAME' not found in defined names
```

**해결:**
```bash
# 정의된 이름 확인 (Python)
uv run python -c "
from openpyxl import load_workbook
wb = load_workbook('templates/base/template.xlsx')
print(list(wb.defined_names.definedName))
"
```

### 8.5 의존성 문제

#### 패키지 설치 실패

**증상:**
```
error: could not find package
```

**해결:**
```bash
# lock 파일 재생성
uv lock

# 전체 재설치
rm -rf .venv
uv sync --all-extras
```

#### Python 버전 불일치

**증상:**
```
requires-python = ">=3.11"
```

**해결:**
```bash
# Python 버전 확인
python --version

# uv로 Python 설치
uv python install 3.11

# 프로젝트 Python 지정
uv python pin 3.11
```

### 8.6 일반적인 해결 패턴

| 문제 유형 | 첫 번째 시도 | 두 번째 시도 |
|-----------|-------------|-------------|
| 서버 시작 실패 | 포트 충돌 확인 | 로그 확인 |
| API 오류 | 환경 변수 확인 | 네트워크 확인 |
| 파일 오류 | 경로/권한 확인 | 백업에서 복구 |
| 테스트 실패 | `uv sync --all-extras` | 격리 테스트 실행 |
| 의존성 오류 | `uv lock && uv sync` | `.venv` 삭제 후 재설치 |

---

## 부록

### A. 로그 스키마

**실행 로그 (`logs/run_<run_id>.json`):**

```json
{
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "job_id": "WO001-L1-a3b2c1d4",
  "started_at": "2024-01-15T09:30:00Z",
  "finished_at": "2024-01-15T09:30:05Z",
  "result": "success",
  "reject_reason": null,
  "reject_context": null,
  "packet_hash": "sha256...",
  "packet_full_hash": "sha256...",
  "warnings": [],
  "definition_version": "1.0",
  "schema_version": "1.0"
}
```

**reject 시 (`result: "rejected"`):**

```json
{
  "result": "rejected",
  "reject_reason": "MISSING_CRITICAL_FIELD",
  "reject_context": {
    "field": "wo_no",
    "message": "Required field 'wo_no' not found in packet.xlsx"
  }
}
```

> `reject_reason` 값은 [3. 에러 대응](#3-에러-대응)의 에러 코드와 동일합니다.

**warnings 배열 항목:**

```json
{
  "code": "PHOTO_DUPLICATE_AUTO_SELECTED",
  "action_id": "photo_select_01_overview",
  "field_or_slot": "overview",
  "original_value": "01_overview.jpg, 01_overview.png",
  "resolved_value": "01_overview.jpg",
  "message": "Multiple files for slot, selected by prefer_order"
}
```

> `code` 값은 [4. 경고 대응](#4-경고-대응)의 경고 코드와 동일합니다.

**슬롯 매칭 결과 (photo_processing[].confidence):**

```json
{
  "photo_processing": [
    {
      "slot_id": "label_serial",
      "action": "mapped",
      "raw_path": "photos/raw/02_label_serial.jpg",
      "derived_path": "photos/derived/label_serial.jpg",
      "confidence": "high",
      "matched_by": "basename_exact",
      "ocr_verified": true,
      "timestamp": "2024-01-15T09:30:00Z"
    },
    {
      "slot_id": "overview",
      "action": "mapped",
      "confidence": "low",
      "matched_by": "key_prefix",
      "warning": "사용자 확인 필요: 파일명이 규칙과 다름",
      "timestamp": "2024-01-15T09:30:00Z"
    }
  ]
}
```

**confidence 값:**
| 값 | 의미 |
|-----|------|
| `high` | basename 정확히 일치 + OCR 검증 완료 |
| `medium` | basename 접두사 일치 |
| `low` | key 접두사만 일치 (확인 필요) |
| `ambiguous` | 여러 슬롯에 매칭 가능 (확인 필요) |

**로그 파일명 규칙:**
- 형식: `run_<run_id 앞 8자리>.json`
- 예: `run_a1b2c3d4.json`

### B. 유용한 명령어

```bash
# 모든 job의 결과 요약
for job in jobs/*/; do
  echo "=== $job ==="
  cat "$job/logs/"run_*.json 2>/dev/null | tail -1 | jq '{job_id, result, reject_reason}'
done

# 최근 실패한 job 찾기
grep -l '"result":"rejected"' jobs/*/logs/*.json

# 특정 에러 코드 검색
grep -r "MISSING_CRITICAL_FIELD" jobs/*/logs/

# 경고가 많은 job 찾기
for job in jobs/*/; do
  count=$(cat "$job/logs/"*.json 2>/dev/null | jq '.warnings | length' | paste -sd+ | bc)
  echo "$job: $count warnings"
done | sort -t: -k2 -rn | head -10
```

### C. 관련 문서

| 문서 | 내용 |
|------|------|
| [spec.md](spec.md) | 시스템 명세 |
| [ADR-0001.md](decisions/ADR-0001.md) | job.json SSOT 결정 배경 |
| [AGENTS.md](AGENTS.md) | AI 코딩 규칙 |
| [definition.yaml](../definition.yaml) | 입력 계약 |
| [configs/README.md](../configs/README.md) | 설정 사용법 |
