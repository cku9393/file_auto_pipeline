# configs/

런타임 설정 파일입니다.

## 설정 파일 역할 분리

| 파일 | 역할 | 수정 주체 |
|------|------|-----------|
| `definition.yaml` | 입력 형식 (Excel/사진 파싱 규칙) | 개발자 (고객사/라인 변경 시) |
| `configs/*.yaml` | 동작/출력 옵션 (락, 로깅, PDF 등) | 운영자/개발자 (환경별 조정) |

> **SSOT 원칙**: 입력 계약은 `definition.yaml`, 출력/런타임은 `configs/*.yaml`

## 파일

| 파일 | 설명 |
|------|------|
| `default.yaml` | 기본 설정 (개발/테스트) |
| `production.yaml` | 프로덕션 오버라이드 |

## 사용법

```bash
# 기본 설정
pixi run pipeline jobs/demo_001

# 프로덕션 설정
pixi run pipeline jobs/demo_001 --config configs/production.yaml
```

## 주요 설정

| 설정 | 설명 | 기본값 |
|------|------|--------|
| `pipeline.lock_timeout_seconds` | SSOT 락 대기 시간 | 2 |
| `features.generate_pdf` | PDF 생성 여부 | false |
| `logging.level` | 로그 레벨 | INFO |
