# System Specification

Manufacturing Documentation Pipeline의 시스템 명세입니다.

> **확장 명세**: 채팅 UI, AI 파싱, 템플릿 라이브러리, Override 시스템 등  
> 확장 기능은 [spec-v2.md](./spec-v2.md)를 참조하세요.
>
> **규범 우선순위**: spec.md(코어) > spec-v2.md(확장)  
> 두 문서가 충돌하면 spec.md가 우선합니다.

## 1. Overview

이 파이프라인은 제조 현장의 검사 데이터(Excel)와 사진을 수집하여 고객용 보고서를 자동 생성합니다.

### 설계 원칙

| 원칙 | 설명 |
|------|------|
| **Fail-fast** | 오류 발생 시 즉시 중단, 조용한 오염 방지 |
| **SSOT** | `job.json`이 Job ID의 단일 진실 원천 |
| **재현성** | 동일 입력 → 동일 출력 (해시로 검증) |
| **유연한 입력** | 고정 템플릿 없이 라벨 기반 추출 |
| **감사 추적** | 모든 실행은 로그와 해시로 추적 가능 |

### 파이프라인 흐름

```
packet.xlsx + photos/raw/
       │
       ▼
   ┌─────────┐
   │ Ingest  │ ─── 라벨 스캔, 측정 테이블 감지
   └────┬────┘
        ▼
   ┌──────────┐
   │Normalize │ ─── 문자열/숫자 정규화, float 감지
   └────┬─────┘
        ▼
   ┌──────────┐
   │ Validate │ ─── 필수 필드/사진 확인, reject 판정
   └────┬─────┘
        ▼
   ┌──────────┐
   │   SSOT   │ ─── job.json 생성/읽기, run_id 발급
   └────┬─────┘
        ▼
   ┌──────────┐
   │  Photos  │ ─── 슬롯 선택, derived 복사, 아카이브
   └────┬─────┘
        ▼
   ┌──────────┐
   │ Hashing  │ ─── packet_hash, packet_full_hash 계산
   └────┬─────┘
        ▼
   ┌──────────┐
   │  Render  │ ─── HTML/PDF 보고서, CSV 생성
   └────┬─────┘
        ▼
   ┌──────────┐
   │ Package  │ ─── deliverables/, logs/ 저장
   └──────────┘
        │
        ▼
   report.html + job.json + logs/
```

---

## 2. Input Contract

### 2.1 Labels & Fields

`definition.yaml`에서 정의하는 필드 스키마입니다.

> **필드명 통일 규칙**: `definition.yaml`의 필드 키(예: `wo_no`, `line`)는  
> 코드, job.json, 로그, 해시 계산 등 **모든 곳에서 동일하게 사용**합니다.  
> 혼란 방지를 위해 `line_id`, `lineId` 등 변형을 금지합니다.

#### 필드 타입

| 타입 | 정규화 | 예시 |
|------|--------|------|
| `token` | strip + 단일 공백 압축 | `"  WO-001  "` → `"WO-001"` |
| `free_text` | strip, 내부 줄바꿈 유지 | 비고, 메모 |
| `number` | `Decimal` 변환, trailing zero 제거 | `"3.140"` → `3.14` |

#### 중요도 (importance)

| 중요도 | NaN/Inf | parse_error | 미존재 |
|--------|---------|-------------|--------|
| `critical` | **reject** | **reject** | **reject** |
| `reference` | **reject** | `null` + warn | `null` + warn |

#### 라벨 별칭 (aliases)

```yaml
fields:
  wo_no:
    type: token
    importance: critical
    aliases: ["WO No", "Work Order", "작업지시번호", "W/O"]
```

동의어 중 하나라도 Excel에서 발견되면 해당 필드로 매핑됩니다.

### 2.2 Photo Slots

사진은 슬롯 기반으로 관리됩니다.

#### 슬롯 정의

```yaml
photos:
  allowed_extensions: [".jpg", ".jpeg", ".png"]
  prefer_order: [".jpg", ".jpeg", ".png"]  # 중복 시 우선순위
  slots:
    - key: overview
      basename: "01_overview"
      required: true
    - key: label_serial
      basename: "02_label_serial"
      required: true
    - key: defect
      basename: "03_defect"
      required: false
```

#### 슬롯 매칭 규칙

1. `photos/raw/`에서 `basename`으로 시작하는 파일 검색
2. 확장자가 `allowed_extensions`에 포함되어야 함
3. 중복 발견 시 `prefer_order`에 따라 선택 + warn
4. `required: true`인 슬롯 누락 시 **reject**

### 2.3 definition.yaml 전체 스키마

```yaml
# definition.yaml
version: "1.0"

fields:
  wo_no:
    type: token
    importance: critical
    aliases: ["WO No", "Work Order", "작업지시번호"]
  
  line:
    type: token
    importance: critical
    aliases: ["Line", "라인"]
  
  part_no:
    type: token
    importance: critical
    aliases: ["Part No", "부품번호", "P/N"]
  
  lot:
    type: token
    importance: critical
    aliases: ["Lot", "로트", "Lot No"]
  
  result:
    type: token
    importance: critical
    aliases: ["Result", "결과", "판정"]
  
  inspector:
    type: token
    importance: reference
    aliases: ["Inspector", "검사자"]
  
  date:
    type: token
    importance: reference
    aliases: ["Date", "검사일", "일자"]
  
  remark:
    type: free_text
    importance: reference
    aliases: ["Remark", "비고", "Notes"]

measurement_table:
  detection:
    headers: ["SPEC", "MEASURED"]  # 이 헤더가 있으면 측정 테이블로 인식
  columns:
    item: { aliases: ["Item", "항목", "No"] }
    spec: { aliases: ["SPEC", "규격", "Specification"] }
    measured: { aliases: ["MEASURED", "측정값", "Actual"] }
    result: { aliases: ["Result", "판정", "OK/NG"] }

photos:
  allowed_extensions: [".jpg", ".jpeg", ".png"]
  prefer_order: [".jpg", ".jpeg", ".png"]
  slots:
    - { key: overview, basename: "01_overview", required: true }
    - { key: label_serial, basename: "02_label_serial", required: true }
    - { key: measurement_setup, basename: "03_measurement_setup", required: false }
    - { key: defect, basename: "04_defect", required: false }
```

---

## 3. Pipeline Phases

### 3.1 Ingest

Excel 파일을 읽어 raw 데이터를 추출합니다.

**입력**: `packet.xlsx`  
**출력**: `RawPacket` (필드 dict + 측정 테이블 rows)

**동작**:
1. 모든 시트 스캔
2. `definition.yaml`의 aliases로 라벨 검색
3. 라벨 우측/하단 셀에서 값 추출
4. `measurement_table.detection.headers`로 측정 테이블 감지
5. 측정 테이블의 각 행을 dict로 수집

### 3.2 Normalize

raw 값을 정규화합니다.

**입력**: `RawPacket`  
**출력**: `NormalizedPacket`

**동작**:

| 타입 | 변환 |
|------|------|
| `token` | `str.strip()` → 연속 공백을 단일 공백으로 |
| `free_text` | `str.strip()` (내부 줄바꿈 유지) |
| `number` | `Decimal(value).normalize()` |

**특수 케이스**:
- `NaN`, `Inf` → **항상 reject** (importance 무관)
- float 입력 감지 시 → 내부 로그 기록 (float_inputs_detected)
- parse_error → importance에 따라 reject 또는 null+warn

### 3.3 Validate

정규화된 데이터의 유효성을 검사합니다.

**입력**: `NormalizedPacket`  
**출력**: `ValidatedPacket` 또는 `PolicyRejectError`

**검사 항목**:
1. `critical` 필드 존재 여부
2. `critical` 필드 값 유효성 (null 불가)
3. `required: true` 사진 슬롯 존재 여부

### 3.4 SSOT (job.json)

Job ID의 단일 진실 원천을 관리합니다.

**입력**: `ValidatedPacket`, job 폴더 경로  
**출력**: `job_id`, `run_id`

**락 정책**:
- 락 방식: **디렉터리 락** (`.job_json.lock/` 디렉터리 생성)
- 기본 timeout: **2초** (40회 × 0.05초 간격)
- 설정: `configs/*.yaml`의 `pipeline.lock_timeout_seconds`로 조정 가능
- timeout 초과 시: `JOB_JSON_LOCK_TIMEOUT` reject

**동작**:
1. `.job_json.lock/` 디렉터리 생성 시도 (락 획득)
2. `job.json` 존재 여부 확인
   - 없으면: 새 `job_id` 생성 (WO + Line + timestamp hash)
   - 있으면: 기존 `job_id` 읽기 + mismatch 검증
3. 새 `run_id` 생성 (UUID v4)
4. `job.json` 원자적 쓰기 (temp 파일 → `os.rename()`)
5. `.job_json.lock/` 디렉터리 삭제 (락 해제)

**mismatch 검증**:
- 기존 `job.json`의 `wo_no`, `line`과 현재 packet 비교
- 불일치 시 `PACKET_JOB_MISMATCH` reject (잘못된 폴더 방지)

**job.json 구조**:
```json
{
  "job_id": "WO001-L1-a3b2c1d4",
  "job_id_version": 1,
  "schema_version": "1.0",
  "created_at": "2024-01-15T09:30:00Z",
  "wo_no": "WO-001",
  "line": "L1"
}
```

> **필드명 규칙**: 입력 필드와 job.json 필드명은 `definition.yaml`의 키와 동일하게 유지.  
> 예: `line` (O), `line_id` (X)

### 3.5 Photos

사진을 슬롯에 따라 선택하고 derived로 복사합니다.

**입력**: `photos/raw/`, 슬롯 정의  
**출력**: `photos/derived/`, 아카이브된 이전 파일

**동작**:
1. 각 슬롯에 대해 `photos/raw/`에서 매칭 파일 검색
2. 중복 시 `prefer_order`로 선택 + warn 로그
3. 기존 `photos/derived/` 파일을 `photos/trash/`로 아카이브
4. 선택된 파일을 `photos/derived/`로 복사
5. 아카이브 실패 시 → **reject** (dirty state 방지)

**safe_move 보장 (아카이브 시)**:

| 보장 | 설명 |
|------|------|
| **원인 보존** | 실패 시 `operation`, `errno`, `error_message` 기록 |
| **dst 충돌 해결** | 동일 파일명 존재 시 `_1`, `_2` 등 suffix 자동 부여 |
| **원자성** | 이동 완료 전 원본 삭제 없음 |
| **fsync 경고** | `fsync` 실패 시 warn (데이터는 보존) |

**아카이브 파일명 규칙**:
```
photos/trash/{original_name}_{timestamp}.{ext}
예: 01_overview_20240115_093000.jpg
```

**실패 시 reject 이유**:
- 아카이브 실패 상태에서 새 파일 복사 시 "이전 버전 복구 불가"
- 이는 감사 추적 불가 → ISO 30301 위반

### 3.6 Hashing

감사 추적용 해시를 계산합니다.

**입력**: `NormalizedPacket`  
**출력**: `packet_hash`, `packet_full_hash`

| 해시 | 포함 필드 | 용도 |
|------|-----------|------|
| `packet_hash` | `critical` + `reference`(number/token만) | pass/fail 동일성 판정 |
| `packet_full_hash` | 모든 필드 (free_text 포함) | 변경 감지, 감사 |

**알고리즘**: SHA-256, 필드를 정렬된 JSON으로 직렬화 후 해시

### 3.7 Render

고객용 보고서를 생성합니다.

**입력**: 모든 이전 단계 결과  
**출력**: `report.html`, `report.pdf` (옵션), `measurements.csv` (조건부)

**report.html 구조**:

| 섹션 | 내용 |
|------|------|
| Header | job_id, run_id, packet_hash, 생성 시각 |
| Summary | PASS/FAIL, 검사 항목 수, 실패 항목 수 |
| Measurements | 핵심 측정값 (최대 8행) |
| Photos | 슬롯별 사진 (derived에서) |
| Footer | packet_full_hash, 파이프라인 버전 |

**조건부 출력**:
- 측정 행 > 8개 → `measurements.csv` 생성
- `--pdf` 플래그 또는 설정 → `report.pdf` 생성

### 3.8 Package

최종 산출물을 정리합니다.

**입력**: 모든 이전 단계 결과  
**출력**: 파일 시스템에 저장된 산출물

**저장 위치**:
```
jobs/<job_folder>/
  job.json
  deliverables/
    report.html
    report.pdf          # 옵션
    measurements.csv    # 8행 초과 시
  photos/
    derived/
    trash/
  logs/
    run_<run_id>.json
```

---

## 4. Error Handling & Reject Policy

### 에러 분류

| 분류 | 처리 | 예시 |
|------|------|------|
| `PolicyRejectError` | 즉시 중단, 로그 기록 | 필수 필드 누락, NaN 감지 |
| `Warning` | 계속 진행, 로그 기록 | 중복 사진 자동 선택 |
| `InternalLog` | 계속 진행, 내부 로그 | float 입력 감지 |

### 에러 코드

| 코드 | 원인 | 복구 방법 |
|------|------|-----------|
| `MISSING_CRITICAL_FIELD` | critical 필드 누락 | packet.xlsx 확인 |
| `INVALID_DATA` | NaN/Inf 감지 | 데이터 수정 |
| `PARSE_ERROR_CRITICAL` | critical 필드 파싱 실패 | 데이터 형식 확인 |
| `MISSING_REQUIRED_PHOTO` | required 사진 슬롯 누락 | photos/raw/ 확인 |
| `JOB_JSON_LOCK_TIMEOUT` | lock 획득 실패 (기본 2초) | 다른 프로세스 종료 대기 |
| `PACKET_JOB_MISMATCH` | WO/Line 불일치 | 올바른 job 폴더 확인 |
| `ARCHIVE_FAILED` | derived 아카이브 실패 | 디스크 공간/권한 확인 |

### 경고(Warning) 시스템

경고는 파이프라인을 중단하지 않지만, **반드시 로그에 기록**되어야 합니다.

#### 경고 코드

| 코드 | 발생 조건 |
|------|-----------|
| `PHOTO_DUPLICATE_AUTO_SELECTED` | 슬롯에 여러 파일, 자동 선택됨 |
| `PARSE_ERROR_REFERENCE` | reference 필드 파싱 실패, null 처리 |
| `PHOTO_OPTIONAL_MISSING` | optional 사진 슬롯 누락 |
| `FSYNC_FAILED` | 파일 동기화 실패 (데이터는 보존) |

#### 경고 필수 컨텍스트

모든 Warning 로그는 다음 필드를 **필수 포함**해야 합니다:

```json
{
  "level": "warning",
  "code": "PHOTO_DUPLICATE_AUTO_SELECTED",
  "action_id": "photo_select_01_overview",
  "field_or_slot": "overview",
  "original_value": "01_overview.jpg, 01_overview.png",
  "resolved_value": "01_overview.jpg",
  "message": "Multiple files for slot 'overview', selected by prefer_order"
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `code` | ✅ | 경고 코드 |
| `action_id` | ✅ | 발생 위치 식별자 (phase_target 형식) |
| `field_or_slot` | ✅ | 관련 필드명 또는 슬롯 키 |
| `original_value` | ✅ | 원본 값 (truncate: 200자) |
| `resolved_value` | 조건부 | 자동 해결된 경우 결과값 |
| `message` | ✅ | 사람이 읽을 수 있는 설명 |

### Reject 철학

> "실패는 기능이다."

조용한 오염보다 명시적 실패가 낫습니다. 모든 reject는:
1. 명확한 에러 코드와 메시지 포함
2. 로그에 기록 (부분 로그라도 저장)
3. 파이프라인 즉시 중단
4. 사용자에게 복구 방법 안내

---

## 5. Versioning

### 버전 종류

| 버전 | 위치 | 변경 시점 |
|------|------|-----------|
| `schema_version` | 로그, job.json | 로그/SSOT 구조 변경 |
| `packet_hash_version` | 로그 | 정규화 규칙 변경 |
| `job_id_version` | job.json | job_id 생성 규칙 변경 |
| `definition_version` | definition.yaml | 필드/슬롯 스키마 변경 |

### 하위 호환성

- `schema_version` 변경 시: 이전 로그 읽기 지원 유지
- `packet_hash_version` 변경 시: 해시 비교 불가 명시
- `job_id_version` 변경 시: 기존 job_id 유지 (신규만 영향)

### 버전 관리 규칙

```
MAJOR.MINOR 형식
- MAJOR: 하위 호환 불가 변경
- MINOR: 하위 호환 가능 변경
```

---

## 6. Testing Strategy

### 테스트 범위

| 레벨 | 대상 | 위치 |
|------|------|------|
| Unit | 개별 모듈 함수 | `tests/unit/` |
| Integration | 파이프라인 전체 흐름 | `tests/integration/` |
| Fixture | 샘플 job 폴더 | `jobs/sample_*` |

### Unit 테스트 대상

- `src/pipeline/ingest.py`: 라벨 스캔, 테이블 감지
- `src/pipeline/normalize.py`: 타입별 정규화, NaN 감지
- `src/pipeline/validate.py`: 필수 필드 검증
- `src/pipeline/ssot.py`: job.json 생성/읽기, lock
- `src/pipeline/photos.py`: 슬롯 매칭, 아카이브
- `src/pipeline/hashing.py`: 해시 계산
- `src/domain/errors.py`: 에러 코드 정의

### 테스트 데이터

```
jobs/
  sample_pass/       # 정상 케이스
    packet.xlsx
    photos/raw/
  sample_fail/       # 실패 케이스 (필수 필드 누락)
  sample_photos/     # 사진 관련 케이스 (중복, 누락)
```

### 실행 방법

```bash
pixi run test           # 전체 테스트
pixi run test-cov       # 커버리지 포함
pixi run check          # lint + test
```

---

## 7. Standards Alignment

이 파이프라인은 다음 국제 표준을 참조합니다.

### IEC/IEEE 82079-1:2019

**사용 정보 작성 원칙**

| 원칙 | 적용 |
|------|------|
| 구조화된 정보 | definition.yaml로 필드 스키마 정의 |
| 일관성 | 정규화 규칙으로 형식 통일 |
| 명확성 | 에러 코드와 메시지로 명확한 피드백 |

### ISO 10013:2021

**문서 관리 시스템**

| 요구사항 | 적용 |
|----------|------|
| 문서 식별 | job_id, run_id로 고유 식별 |
| 버전 관리 | schema_version, packet_hash_version |
| 변경 추적 | 로그, 해시로 변경 감지 |

### ISO 30301:2019

**기록 관리**

| 요구사항 | 적용 |
|----------|------|
| 진본성 | packet_hash로 무결성 검증 |
| 신뢰성 | SSOT로 job_id 불변 보장 |
| 무결성 | 해시 + 로그로 변조 감지 |
| 가용성 | 구조화된 폴더로 접근 용이 |

---

## Appendix: Quick Reference

### 필수 입력

| 항목 | 경로 | 필수 |
|------|------|------|
| 검사 데이터 | `packet.xlsx` | ✅ |
| 개요 사진 | `photos/raw/01_overview.*` | ✅ |
| 라벨 사진 | `photos/raw/02_label_serial.*` | ✅ |

### 출력 파일

| 파일 | 경로 | 조건 |
|------|------|------|
| SSOT | `job.json` | 항상 |
| 보고서 | `deliverables/report.html` | 항상 |
| PDF | `deliverables/report.pdf` | --pdf 옵션 |
| 측정 CSV | `deliverables/measurements.csv` | 8행 초과 |
| 실행 로그 | `logs/run_<run_id>.json` | 항상 |

### CLI 옵션

| 옵션 | 설명 |
|------|------|
| `--rebuild-derived` | derived 사진 재생성 |
| `--autofix-photos` | 사진 슬롯 자동 수정 |
| `--pdf` / `--no-pdf` | PDF 보고서 생성 ON/OFF |
| `--verbose` | 상세 로그 출력 |
| `--config <path>` | 설정 파일 경로 (기본: `configs/default.yaml`) |

> **우선순위**: CLI 플래그 > config 파일 > 기본값  
> - `--pdf`: config 무시하고 강제 ON  
> - `--no-pdf`: config 무시하고 강제 OFF  
> - 둘 다 없으면: `features.generate_pdf` 값 사용
