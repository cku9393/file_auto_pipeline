# File Auto Pipeline

제조 현장의 검사 데이터를 수집하고, 정규화하여 고객용 보고서를 자동 생성하는 파이프라인입니다.

> **프로젝트명**: `file-auto-pipeline` (pyproject.toml 기준)

## Why This Exists

- 고객에게 **1페이지 검사/출하 패킷**을 일관되게 제공
- 운영팀은 **SSOT(`job.json`)** + **run별 로그(`run_id`)**로 사고 대응
- 입력은 "엑셀 자유형"이지만 **최소 계약(`definition.yaml`)**을 만족해야 함
- 해시/버전으로 "왜 같은 입력인데 결과가 달라졌나"를 즉시 추적
- 사진/derived는 슬롯별 단일본 보장 + 아카이브(trash)로 복구 가능

## 요구사항

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (권장 패키지 매니저)

## 설치

### uv 설치 (최초 1회)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 프로젝트 설정

```bash
git clone https://github.com/your-org/file-auto-pipeline.git
cd file-auto-pipeline

# 의존성 설치 (dev 포함)
uv sync --all-extras --dev
```

## 빠른 시작

```bash
# 테스트 실행
uv run pytest tests/ -v

# 개발 서버 실행
uv run uvicorn src.app.main:app --reload --host 0.0.0.0 --port 8000

# 코드 품질 검사
uv run ruff check src/ tests/
uv run mypy src/
```

## 테스트

```bash
# 전체 테스트
uv run pytest tests/ -v

# 커버리지 포함
uv run pytest tests/ --cov=src --cov-report=term-missing

# 특정 테스트만
uv run pytest tests/unit/ -v              # 유닛 테스트
uv run pytest tests/integration/ -v       # 통합 테스트
uv run pytest tests/e2e/ -v               # E2E 테스트
```

### 테스트 현황

| 카테고리 | 테스트 수 | 상태 |
|----------|-----------|------|
| Unit | 336 | ✅ 통과 |
| Integration | 26 | ✅ 통과 |
| E2E | 63 | ✅ 통과 |
| **총계** | **425** | ✅ 통과 |

## Input Contract: `definition.yaml`

`definition.yaml`은 **입력 파싱 및 검증의 SSOT**입니다.

### 필드 정의

```yaml
fields:
  wo_no:    { type: token,     importance: critical }
  measured: { type: number,    importance: critical }
  remark:   { type: free_text, importance: reference }

photos:
  allowed_extensions: [".jpg", ".jpeg", ".png"]
  slots:
    - { key: overview,      basename: "01_overview",      required: true }
    - { key: label_serial,  basename: "02_label_serial",  required: true }
    - { key: defect,        basename: "03_defect",        required: false }
```

### 필드 중요도와 에러 처리

| 상황 | critical | reference |
|------|----------|-----------|
| `NaN/Inf` | reject | reject |
| `parse_error` | reject | `null` + warn |

## SSOT & IDs

| ID/Hash | 생성 시점 | 변경 여부 |
|---------|-----------|-----------|
| `job_id` | job 최초 실행 | **불변** |
| `run_id` | 매 실행마다 | 항상 새로 발급 |
| `packet_hash` | 실행 시 계산 | 입력 변경 시 변경 |
| `packet_full_hash` | 실행 시 계산 | 입력 변경 시 변경 |

## 폴더 구조

```
repo/
├── .github/workflows/    # CI/CD
│   └── ci.yml
├── src/
│   ├── core/             # 핵심 로직 (SSOT, 해시, 사진)
│   ├── domain/           # 스키마, 에러
│   ├── render/           # 문서 렌더링 (DOCX, XLSX)
│   ├── templates/        # 템플릿 관리 코드
│   └── app/              # FastAPI 웹앱
├── templates/            # 템플릿 데이터
├── tests/
│   ├── unit/             # 유닛 테스트
│   ├── integration/      # 통합 테스트
│   └── e2e/              # E2E 테스트
├── spec-v2.md            # 시스템 명세 (루트)
├── docs/
│   └── runbook.md        # 운영 매뉴얼
├── AGENTS.md             # AI 에이전트 규칙
├── definition.yaml       # 입력 계약 SSOT
└── pyproject.toml        # 프로젝트 설정
```

## Failure is a Feature (Fail-fast)

이 파이프라인은 **조용한 오염을 방지**하기 위해 명시적으로 실패합니다.

| 에러 코드 | 원인 | 의미 |
|-----------|------|------|
| `JOB_JSON_LOCK_TIMEOUT` | 다른 프로세스가 SSOT 생성 중 | 동시 실행 충돌 |
| `PACKET_JOB_MISMATCH` | 폴더와 packet 내용 불일치 | 잘못된 job 폴더 |
| `INVALID_DATA` | NaN/Inf 감지 | 수치 데이터 오염 |
| `ARCHIVE_FAILED` | derived 아카이브 실패 | dirty state 방지 |
| `MISSING_CRITICAL_FIELD` | 필수 필드 누락 | 입력 계약 위반 |
| `MISSING_REQUIRED_PHOTO` | 필수 사진 슬롯 누락 | 입력 계약 위반 |

## 주요 커맨드

| 커맨드 | 설명 |
|--------|------|
| `uv run pytest tests/` | 전체 테스트 실행 |
| `uv run ruff check src/` | 코드 린팅 |
| `uv run ruff format src/` | 코드 포맷팅 |
| `uv run mypy src/` | 타입 검사 |
| `uv run uvicorn src.app.main:app --reload` | 개발 서버 |

## CI/CD

GitHub Actions로 자동 테스트 및 품질 검사가 실행됩니다:

- **Lint**: Ruff + MyPy
- **Test**: pytest + coverage
- **Matrix**: Python 3.11, 3.12 호환성 검증
- **Security**: Bandit 보안 스캔

## 문서

| 문서 | 설명 |
|------|------|
| [spec-v2.md](spec-v2.md) | 시스템 명세 |
| [runbook.md](runbook.md) | 운영 매뉴얼 |
| [AGENTS.md](AGENTS.md) | AI 코딩 에이전트 규칙 |
| [ADR-0001.md](ADR-0001.md) | job.json SSOT 결정 |
| [ADR-0002.md](ADR-0002.md) | 템플릿 라이브러리 설계 |
| [ADR-0003.md](ADR-0003.md) | AI 파싱 레이어 설계 |

## 라이선스

MIT License
