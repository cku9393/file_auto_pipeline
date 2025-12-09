# AGENTS.md

AI 코딩 에이전트(Claude, Cursor, Copilot 등)가 이 프로젝트에서 작업할 때 따라야 할 규칙입니다.

## 프로젝트 개요

제조 현장 검사 데이터(Excel + 사진)를 수집하여 고객용 보고서를 자동 생성하는 파이프라인입니다.

### 핵심 원칙 (절대 위반 금지)

| 원칙 | 설명 |
|------|------|
| **Fail-fast** | 오류 시 즉시 중단, 조용한 오염 방지 |
| **SSOT** | job.json = Job ID의 유일한 진실 원천 |
| **필드명 통일** | `definition.yaml` 키와 동일하게 사용 (변형 금지) |
| **재현성** | 동일 입력 → 동일 출력, 해시로 검증 |

## 필수 문서 읽기

코드 작성 전 반드시 읽어야 할 문서:

```
spec-v2.md            # 시스템 명세 (파이프라인 단계, 에러 정책)
definition.yaml       # 입력 계약 SSOT (필드/사진 스키마)
default.yaml          # 런타임 설정 (프로젝트 루트)
ADR-0001.md           # job.json SSOT 결정 배경
ADR-0002.md           # 템플릿 라이브러리 설계
ADR-0003.md           # AI 파싱 레이어 설계
```

## 금지 사항

### 절대 금지

```python
# ❌ 필드명 변형 금지
line_id = data["line"]      # WRONG: line_id 사용
lineId = data["line"]       # WRONG: camelCase 변형

# ✅ definition.yaml 키 그대로 사용
line = data["line"]         # CORRECT
```

```python
# ❌ 조용한 실패 금지
try:
    value = parse(data)
except:
    value = None            # WRONG: 에러 삼킴

# ✅ 명시적 실패
try:
    value = parse(data)
except ParseError as e:
    raise PolicyRejectError("PARSE_ERROR_CRITICAL", field=field, cause=e)
```

```python
# ❌ job_id 수정 금지
job_data["job_id"] = new_id  # WRONG: job_id는 불변

# ✅ run_id만 새로 발급
job_data["run_id"] = str(uuid.uuid4())  # CORRECT
```

```python
# ❌ float 직접 사용 금지 (숫자 필드)
measured = float(raw_value)  # WRONG: 정밀도 손실

# ✅ Decimal 사용
from decimal import Decimal
measured = Decimal(str(raw_value)).normalize()  # CORRECT
```

### NaN/Inf 처리

```python
# NaN/Inf는 importance와 무관하게 항상 reject
import math

if math.isnan(value) or math.isinf(value):
    raise PolicyRejectError("INVALID_DATA", field=field, value=value)
```

## 파일 구조

```
repo/
├── definition.yaml      # 입력 계약 SSOT (수정 시 definition_version 업데이트)
├── default.yaml         # 기본 런타임 설정 (프로젝트 루트)
├── src/
│   ├── domain/          # 도메인 스키마 & 에러 정의
│   │   ├── errors.py    # PolicyRejectError, ErrorCodes
│   │   └── schemas.py   # NormalizedPacket, RunLog, IntakeSession
│   ├── core/            # 핵심 안전 로직 (파이프라인 공통)
│   │   ├── ssot_job.py  # job.json 관리 (lock, atomic_write, mismatch)
│   │   ├── ids.py       # job_id/run_id 생성
│   │   ├── hashing.py   # packet_hash, packet_full_hash
│   │   ├── photos.py    # safe_move, select_photo_for_slot
│   │   └── logging.py   # RunLog 관리
│   ├── render/          # 문서 렌더링
│   │   ├── word.py      # DocxRenderer (docxtpl)
│   │   └── excel.py     # ExcelRenderer (Named Range 우선)
│   ├── templates/       # 템플릿 관리 코드 ⚠️ templates/ 데이터와 구분
│   │   ├── manager.py   # TemplateManager (source/ 불변성 보장)
│   │   └── scaffolder.py # 2단계 스캐폴딩 (auto/semi-auto)
│   └── app/             # FastAPI 웹앱 (UI + AI 파싱)
│       ├── main.py      # FastAPI 앱 진입점
│       ├── config.py    # 설정 관리
│       ├── providers/   # 외부 AI 서비스
│       │   ├── gemini.py   # OCR (FALLBACK vs REJECT 정책)
│       │   └── anthropic.py # 필드 추출 LLM (Claude)
│       ├── services/    # 비즈니스 로직
│       │   ├── intake.py   # IntakeSession (append-only)
│       │   ├── extract.py  # Regex → LLM 순서
│       │   └── validate.py # 최종 검증
│       ├── routes/      # API 라우트
│       ├── prompts/     # AI 프롬프트 텍스트
│       ├── templates/   # Jinja2 HTML ⚠️ 템플릿 코드와 구분
│       └── static/      # CSS/JS
│
├── templates/           # ⚠️ 템플릿 데이터 저장소 (src/templates/와 구분!)
│   ├── base/            # 기본 템플릿 (manifest.yaml)
│   │   └── <template_id>/
│   │       ├── manifest.yaml
│   │       └── source/  # 원본 파일 (chmod 0o444, 불변)
│   └── custom/          # 사용자 정의 템플릿
│
├── jobs/                # 작업 데이터 저장소
│   └── <job_id>/
│       ├── job.json     # SSOT
│       ├── run_<run_id>/
│       └── photos/
│
├── tests/
│   ├── unit/
│   │   └── test_core/   # core/ 유닛 테스트
│   └── integration/
└── tools/               # CLI 유틸리티
```

### ⚠️ 3개의 templates 폴더 구분

| 경로 | 용도 | 내용물 |
|------|------|--------|
| `src/templates/` | **코드** | manager.py, scaffolder.py |
| `templates/` (루트) | **데이터** | base/, custom/, manifest.yaml |
| `src/app/templates/` | **UI** | Jinja2 HTML (base.html, chat.html 등) |

**절대 혼동 금지!** 각 폴더의 역할이 완전히 다릅니다.

## 에러 처리 규칙

### PolicyRejectError (즉시 중단)

```python
# src/domain/errors.py 참조
class PolicyRejectError(Exception):
    def __init__(self, code: str, **context):
        self.code = code
        self.context = context
```

**사용 시점:**
- `critical` 필드 누락/파싱 실패
- NaN/Inf 감지
- `required` 사진 슬롯 누락
- job.json mismatch
- 락 timeout

### Warning (계속 진행, 로그 기록)

```python
# 경고 필수 컨텍스트
warn_log = {
    "level": "warning",
    "code": "PHOTO_DUPLICATE_AUTO_SELECTED",
    "action_id": "photo_select_01_overview",
    "field_or_slot": "overview",
    "original_value": "01_overview.jpg, 01_overview.png",
    "resolved_value": "01_overview.jpg",
    "message": "Multiple files for slot, selected by prefer_order"
}
```

**사용 시점:**
- `reference` 필드 파싱 실패 → null 처리
- 사진 슬롯 중복 → 자동 선택
- optional 사진 누락

## SSOT 모듈 (src/core/ssot_job.py)

### 락 관리 (컨텍스트 매니저)

```python
import os
import time
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def job_lock(job_dir: Path, config: dict):
    """
    job.json 접근을 위한 디렉터리 락.
    
    사용법:
        with job_lock(job_dir, config):
            # job.json 읽기/쓰기
    
    보장:
    - 락 획득: os.mkdir() 원자적 생성
    - 락 해제: 정상/예외 모두 rmdir() 호출
    - timeout: config 기반 재시도
    """
    lock_dir = job_dir / config["paths"]["lock_dir"]
    interval = config["pipeline"]["lock_retry_interval"]
    max_retries = config["pipeline"]["lock_max_retries"]
    
    # 락 획득
    acquired = False
    for attempt in range(max_retries):
        try:
            os.mkdir(lock_dir)
            acquired = True
            break
        except FileExistsError:
            time.sleep(interval)
    
    if not acquired:
        raise PolicyRejectError(
            "JOB_JSON_LOCK_TIMEOUT",
            job_dir=str(job_dir),
            attempts=max_retries,
            total_wait=max_retries * interval
        )
    
    try:
        yield lock_dir
    finally:
        # 락 해제 (정상/예외 모두)
        try:
            os.rmdir(lock_dir)
        except OSError:
            pass  # 이미 삭제됨 or 다른 문제 - 무시
```

**사용 예시:**

```python
with job_lock(job_dir, config):
    if job_json_path.exists():
        existing = json.loads(job_json_path.read_text())
        verify_mismatch(existing, current_packet)
        job_id = existing["job_id"]
    else:
        job_id = generate_job_id(current_packet)
        atomic_write_json(job_json_path, {
            "job_id": job_id,
            "job_id_version": 1,
            "schema_version": "1.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "wo_no": current_packet["wo_no"],
            "line": current_packet["line"]
        })
```

### 원자적 쓰기

```python
import json
import os
import tempfile
from pathlib import Path

def atomic_write_json(path: Path, data: dict):
    """
    원자적 JSON 쓰기.
    
    보장:
    - 중간 상태 없음: temp → rename
    - 실패 시 cleanup: temp 파일 삭제
    - 기존 파일 보존: rename 실패 시 원본 유지
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=dir_path,
            suffix='.tmp',
            delete=False,
            encoding='utf-8'
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path = Path(f.name)
        
        os.rename(temp_path, path)  # 원자적
        
    except Exception:
        # 실패 시 temp 파일 정리
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
```

### Mismatch 검증

```python
def verify_mismatch(existing: dict, current: dict):
    for key in ["wo_no", "line"]:
        if existing.get(key) != current.get(key):
            raise PolicyRejectError(
                "PACKET_JOB_MISMATCH",
                field=key,
                existing=existing.get(key),
                current=current.get(key)
            )
```

## 해시 계산 규칙

### packet_hash (판정 동일성)

```python
import hashlib
import json
import yaml
from pathlib import Path
from typing import Set

def load_field_types(definition_path: Path) -> dict[str, str]:
    """definition.yaml에서 필드별 타입 로드"""
    with open(definition_path) as f:
        definition = yaml.safe_load(f)
    
    return {
        field_name: field_def["type"]
        for field_name, field_def in definition.get("fields", {}).items()
    }

def get_excluded_fields(
    field_types: dict[str, str],
    exclude_types: list[str]
) -> Set[str]:
    """제외할 필드명 집합 반환"""
    return {
        field_name
        for field_name, field_type in field_types.items()
        if field_type in exclude_types
    }

def compute_packet_hash(
    data: dict,
    config: dict,
    definition_path: Path
) -> str:
    """
    판정 동일성 해시 계산.
    
    - free_text 필드 제외 (remark 등)
    - 정렬된 키로 직렬화
    - SHA-256
    """
    exclude_types = config["hashing"]["exclude_from_packet_hash"]  # ["free_text"]
    field_types = load_field_types(definition_path)
    excluded_fields = get_excluded_fields(field_types, exclude_types)
    
    # 제외 필드 필터링
    filtered = {
        k: v for k, v in data.items()
        if k not in excluded_fields
    }
    
    serialized = json.dumps(filtered, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()
```

### packet_full_hash (변경 감지)

```python
def compute_packet_full_hash(data: dict) -> str:
    """
    전체 필드 해시 계산 (감사/변경 감지용).
    
    - 모든 필드 포함 (free_text 포함)
    - 정렬된 키로 직렬화
    - SHA-256
    """
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()
```

**사용 예시:**

```python
# packet_hash: remark 변경해도 동일
packet_hash = compute_packet_hash(normalized_data, config, DEFINITION_PATH)

# packet_full_hash: remark 변경 시 다름
packet_full_hash = compute_packet_full_hash(normalized_data)

# 로그에 기록
run_log["packet_hash"] = packet_hash
run_log["packet_full_hash"] = packet_full_hash
```

## 사진 처리 규칙

### safe_move (아카이브)

```python
import os
import shutil
import errno
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

@dataclass
class MoveResult:
    success: bool
    src: Path
    dst: Optional[Path] = None
    operation: Optional[str] = None
    errno_code: Optional[int] = None
    error_message: Optional[str] = None
    fsync_warning: bool = False

def safe_move(src: Path, dst_dir: Path, logger) -> MoveResult:
    """
    보장:
    - 원인 보존: 실패 시 operation/errno/message 기록
    - dst 충돌 해결: 동일 파일명 존재 시 suffix 추가
    - 원자성: 이동 완료 전 원본 삭제 없음
    - fsync 경고: fsync 실패 시 warn (데이터는 보존)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_name = f"{src.stem}_{timestamp}{src.suffix}"
    dst = dst_dir / dst_name
    
    # dst 충돌 해결
    counter = 1
    while dst.exists():
        dst_name = f"{src.stem}_{timestamp}_{counter}{src.suffix}"
        dst = dst_dir / dst_name
        counter += 1
    
    # 이동 시도 (원인 보존)
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))  # 먼저 복사 (원자성)
    except OSError as e:
        return MoveResult(
            success=False,
            src=src,
            operation="copy",
            errno_code=e.errno,
            error_message=str(e)
        )
    
    # fsync 시도 (경고만, 실패해도 계속)
    fsync_warning = False
    try:
        fd = os.open(str(dst), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        fsync_warning = True
        logger.warning({
            "code": "FSYNC_FAILED",
            "action_id": f"safe_move_{src.name}",
            "field_or_slot": src.stem,
            "original_value": str(dst),
            "message": f"fsync failed: {e}, data preserved"
        })
    
    # 원본 삭제 (복사 성공 후에만)
    try:
        src.unlink()
    except OSError as e:
        return MoveResult(
            success=False,
            src=src,
            dst=dst,
            operation="unlink_source",
            errno_code=e.errno,
            error_message=str(e)
        )
    
    return MoveResult(
        success=True,
        src=src,
        dst=dst,
        fsync_warning=fsync_warning
    )
```

**사용 예시:**

```python
result = safe_move(old_derived, trash_dir, logger)
if not result.success:
    raise PolicyRejectError(
        "ARCHIVE_FAILED",
        operation=result.operation,
        errno=result.errno_code,
        message=result.error_message,
        src=str(result.src)
    )
```

## 테스트 규칙

### 테스트 파일 위치

```
tests/
├── conftest.py              # 공통 fixture
├── unit/
│   ├── test_core/           # core/ 모듈 테스트
│   │   ├── test_ssot_job.py # job_lock, atomic_write, mismatch
│   │   ├── test_ids.py      # job_id/run_id 생성
│   │   ├── test_hashing.py  # packet_hash 재현성
│   │   ├── test_photos.py   # safe_move, fsync warn
│   │   └── test_logging.py  # RunLog 관리
│   ├── test_render/         # render/ 모듈 테스트
│   │   ├── test_word.py
│   │   └── test_excel.py
│   └── test_templates/      # templates/ 코드 테스트
│       ├── test_manager.py
│       └── test_scaffolder.py
└── integration/
    └── test_pipeline.py
```

### 테스트 네이밍

```python
def test_normalize_token_strips_whitespace():
    """token 타입은 앞뒤 공백을 제거해야 함"""
    pass

def test_validate_rejects_nan_in_critical_field():
    """critical 필드에 NaN이 있으면 reject"""
    pass

def test_ssot_mismatch_raises_error():
    """기존 job.json과 wo_no가 다르면 PACKET_JOB_MISMATCH"""
    pass
```

### Fixture 사용

```python
# tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def sample_pass_job(tmp_path):
    """정상 케이스 job 폴더"""
    job_dir = tmp_path / "sample_pass"
    job_dir.mkdir()
    # packet.xlsx, photos/raw/ 생성
    return job_dir

@pytest.fixture
def sample_fail_job(tmp_path):
    """필수 필드 누락 케이스"""
    job_dir = tmp_path / "sample_fail"
    job_dir.mkdir()
    return job_dir
```

## 커밋 메시지 규칙

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

| Type | 설명 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 변경 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, 설정 변경 |

### 예시

```
feat(pipeline): add NaN detection in normalize phase

- Detect NaN/Inf in number fields
- Reject with INVALID_DATA error code
- Log original value for debugging

Closes #123
```

## 주의사항

### definition.yaml 수정 시

1. `definition_version` 업데이트 필수
2. spec.md 동기화 확인
3. 관련 테스트 추가/수정

### default.yaml 수정 시

1. 새 설정 키 추가 시 주석 필수
2. spec-v2.md와 일관성 확인

### 에러 코드 추가 시

1. `src/domain/errors.py`에 정의
2. spec.md의 에러 코드 표에 추가
3. runbook.md에 복구 방법 추가

## 질문이 있으면

1. `spec-v2.md` 먼저 확인
2. `ADR-*.md` 결정 배경 확인
3. 그래도 불명확하면 주석으로 TODO 남기고 진행

## 테스트 실행

```bash
# 전체 테스트
uv run pytest tests/ -v

# 특정 모듈 테스트
uv run pytest tests/unit/test_core/ -v

# 커버리지 포함
uv run pytest tests/ --cov=src --cov-report=term-missing

# 코드 품질 검사
uv run ruff check src/ tests/
uv run mypy src/
```
