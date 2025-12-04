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
4. [경고 대응](#4-경고-대응)
5. [락 문제 해결](#5-락-문제-해결)
6. [백업 및 복구](#6-백업-및-복구)
7. [긴급 대응](#7-긴급-대응)
8. [트러블슈팅](#8-트러블슈팅)

---

## 1. 일상 운영

### 1.1 파이프라인 실행

```bash
# 기본 실행
pixi run generate jobs/<job_folder>

# 프로덕션 설정
pixi run generate jobs/<job_folder> --config configs/production.yaml

# PDF 포함
pixi run generate jobs/<job_folder> --pdf

# 템플릿 지정 (Planned)
pixi run generate jobs/<job_folder> --template inspection/customer_a

# Override 허용 (Planned)
pixi run generate jobs/<job_folder> --allow-override

# derived 사진 재생성
pixi run generate jobs/<job_folder> --rebuild-derived
```

### 1.2 실행 전 체크리스트

| # | 확인 사항 | 명령어/방법 |
|---|-----------|-------------|
| 1 | packet.xlsx 존재 | `ls jobs/<folder>/packet.xlsx` |
| 2 | 필수 사진 존재 | `ls jobs/<folder>/photos/raw/01_overview.* 02_label_serial.*` |
| 3 | 디스크 공간 | `df -h` (최소 100MB 권장) |
| 4 | 락 없음 | `ls -la jobs/<folder>/.job_json.lock` (없어야 정상) |

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
├── unit/                    # 유닛 테스트 (336+ 테스트)
│   ├── test_core/          # Core 모듈 (98 테스트)
│   ├── test_render/        # Render 모듈 (28 테스트)
│   ├── test_templates/     # Templates 모듈 (53 테스트)
│   └── test_app/           # App 모듈 (157 테스트)
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

---

## 3. 에러 대응

### 에러 코드 Quick Reference

| 코드 | 원인 | 긴급도 | 대응 |
|------|------|--------|------|
| `MISSING_CRITICAL_FIELD` | 필수 필드 누락 | 🔴 높음 | packet.xlsx 수정 |
| `INVALID_DATA` | NaN/Inf 감지 | 🔴 높음 | 측정값 확인 |
| `PARSE_ERROR_CRITICAL` | 필수 필드 파싱 실패 | 🔴 높음 | 데이터 형식 확인 |
| `MISSING_REQUIRED_PHOTO` | 필수 사진 누락 | 🔴 높음 | photos/raw/ 확인 |
| `JOB_JSON_LOCK_TIMEOUT` | 락 획득 실패 | 🟡 중간 | [락 문제 해결](#4-락-문제-해결) 참조 |
| `PACKET_JOB_MISMATCH` | WO/Line 불일치 | 🟡 중간 | 올바른 폴더 확인 |
| `ARCHIVE_FAILED` | 아카이브 실패 | 🔴 높음 | 디스크/권한 확인 |

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
   pixi run pipeline jobs/<folder>
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

## 4. 경고 대응

경고는 파이프라인을 중단하지 않지만, 로그에 기록됩니다.

### 경고 코드 Quick Reference

| 코드 | 의미 | 조치 필요 |
|------|------|-----------|
| `PHOTO_DUPLICATE_AUTO_SELECTED` | 슬롯에 여러 파일, 자동 선택 | ⚠️ 확인 권장 |
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
pixi run pipeline jobs/<folder>
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
pixi run pipeline jobs/demo_001 --rebuild-derived
```

**job.json 유실 시:**
```bash
# ⚠️ 새 job_id 생성됨
rm jobs/<folder>/job.json  # 이미 없으면 생략
pixi run pipeline jobs/<folder>
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
pixi run python --version
pixi run python -c "import openpyxl; import jinja2; print('OK')"
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

# 다른 job 테스트
pixi run demo
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
echo $ANTHROPIC_API_KEY
echo $GOOGLE_API_KEY

# .env 파일 확인
cat .env

# 환경 변수 설정
export ANTHROPIC_API_KEY="your-key-here"
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
