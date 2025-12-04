# Architecture Decision Records (ADR)

이 폴더에는 프로젝트의 주요 아키텍처 결정을 기록합니다.

## ADR 목록

| ADR | 제목 | 상태 |
|-----|------|------|
| [ADR-0001](ADR-0001.md) | job.json을 Job ID의 SSOT로 사용 | Accepted |

## ADR 작성 규칙

### 파일명

```
ADR-NNNN.md
```

### 구조

```markdown
# ADR-NNNN: 제목

| 항목 | 내용 |
|------|------|
| **상태** | Proposed / Accepted / Deprecated / Superseded |
| **작성일** | YYYY-MM-DD |
| **결정자** | 이름/팀 |

## Context (배경)
왜 이 결정이 필요한가?

## Decision (결정)
무엇을 결정했는가?

## Consequences (결과)
이 결정의 긍정적/부정적 결과는?
```

### 상태 정의

| 상태 | 의미 |
|------|------|
| `Proposed` | 검토 중 |
| `Accepted` | 채택됨 |
| `Deprecated` | 더 이상 유효하지 않음 |
| `Superseded` | 다른 ADR로 대체됨 |

## 참고

- [ADR GitHub](https://adr.github.io/)
- [Michael Nygard의 ADR 제안](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
