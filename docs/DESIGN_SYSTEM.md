# File Auto Pipeline - Design System
## 제조 현장용 UI 디자인 시스템

**목표**: 밝은 조명 환경, 태블릿 터치 입력, 빠른 상태 파악에 최적화

---

## 색상 팔레트 (Color Palette)

### Primary - Industrial Blue
제조 현장의 신뢰성과 정확성을 표현

```
Primary 50:  #eff6ff  (배경, 호버)
Primary 100: #dbeafe  (비활성)
Primary 200: #bfdbfe  (보조)
Primary 500: #3b82f6  (기본 - 현재 #2563eb보다 밝음)
Primary 600: #2563eb  (호버)
Primary 700: #1d4ed8  (눌림)
Primary 900: #1e3a8a  (텍스트)
```

**변경 이유**: 더 밝고 선명한 파란색으로 현장에서 가독성 향상

### Success - Production Green
작업 완료, 합격 판정

```
Success 50:  #f0fdf4
Success 100: #dcfce7
Success 500: #22c55e  (기본 - 현재 #16a34a보다 밝음)
Success 600: #16a34a  (호버)
Success 700: #15803d
Success 900: #14532d  (텍스트)
```

### Warning - Attention Orange
주의 필요, 확인 대기

```
Warning 50:  #fffbeb
Warning 100: #fef3c7
Warning 500: #f59e0b  (기본 - 현재 #d97706보다 밝음)
Warning 600: #d97706  (호버)
Warning 700: #b45309
Warning 900: #78350f  (텍스트)
```

### Error - Critical Red
불합격, 오류, 긴급

```
Error 50:  #fef2f2
Error 100: #fee2e2
Error 500: #ef4444  (기본 - 현재 #dc2626보다 밝음)
Error 600: #dc2626  (호버)
Error 700: #b91c1c
Error 900: #7f1d1d  (텍스트)
```

### Neutral - Gray Scale
텍스트, 배경, 구분선

```
Gray 25:  #fcfcfd  (최상위 배경)
Gray 50:  #f9fafb  (배경)
Gray 100: #f3f4f6  (비활성 배경)
Gray 200: #e5e7eb  (구분선)
Gray 300: #d1d5db  (보더)
Gray 400: #9ca3af  (Placeholder)
Gray 500: #6b7280  (보조 텍스트)
Gray 600: #4b5563  (부제목)
Gray 700: #374151  (본문 - 현장용으로 더 진함)
Gray 800: #1f2937  (제목)
Gray 900: #111827  (강조)
```

### Status Colors (제조 현장 특화)

```
In Progress:  #8b5cf6  (보라 - 작업 중)
Pending:      #f59e0b  (주황 - 대기)
Completed:    #22c55e  (초록 - 완료)
Failed:       #ef4444  (빨강 - 실패)
Inspection:   #3b82f6  (파랑 - 검사 중)
```

---

## 타이포그래피 (Typography)

### Font Family

```css
/* Primary: Pretendard (한글 최적화) */
font-family: "Pretendard Variable", Pretendard, -apple-system,
             BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

/* Monospace: 코드, 숫자 */
font-family: "JetBrains Mono", "SF Mono", Monaco,
             "Cascadia Code", Consolas, monospace;
```

**변경 이유**:
- Pretendard: 한글 가독성이 시스템 폰트보다 우수
- 숫자/코드용 Monospace: WO 번호, LOT 번호 구분 용이

### Type Scale (1.250 - Major Third)

제조 현장 환경을 고려한 더 큰 사이즈

```
Display:  3.052rem (48.83px) - 대시보드 헤더
H1:       2.441rem (39.06px) - 페이지 제목
H2:       1.953rem (31.25px) - 섹션 제목
H3:       1.563rem (25px)    - 카드 제목
H4:       1.25rem  (20px)    - 서브 헤더
Body L:   1.125rem (18px)    - 큰 본문 (기본 - 현장용 확대)
Body M:   1rem     (16px)    - 일반 본문
Body S:   0.875rem (14px)    - 보조 텍스트
Caption:  0.75rem  (12px)    - 레이블, 메타
```

**변경 이유**: 기본 Body를 18px로 확대하여 현장에서 가독성 향상

### Font Weight

```
Light:    300  (비활성 텍스트)
Regular:  400  (본문)
Medium:   500  (강조, 버튼)
Semibold: 600  (제목)
Bold:     700  (중요 정보)
```

### Line Height

```
Tight:   1.25  (제목)
Normal:  1.5   (본문 - 1.6에서 조정)
Relaxed: 1.75  (긴 텍스트)
```

---

## 간격 시스템 (Spacing)

**4px 기반 시스템** (rem 대신 고정 px 사용 - 현장 일관성)

```
Space 1:  4px    (0.25rem)  - 밀집 요소
Space 2:  8px    (0.5rem)   - 작은 간격
Space 3:  12px   (0.75rem)  - 기본 내부 간격
Space 4:  16px   (1rem)     - 기본 외부 간격
Space 5:  20px   (1.25rem)  - 중간 간격
Space 6:  24px   (1.5rem)   - 섹션 간 간격
Space 8:  32px   (2rem)     - 큰 섹션
Space 10: 40px   (2.5rem)   - 페이지 상단
Space 12: 48px   (3rem)     - 주요 영역
Space 16: 64px   (4rem)     - 특별 간격
```

**터치 타겟 최소 크기**: 44px × 44px (Apple Human Interface Guidelines)

---

## Border Radius

```
Radius XS:  4px   - 작은 요소 (badge, chip)
Radius S:   6px   - 버튼, 인풋
Radius M:   8px   - 카드 (현재)
Radius L:   12px  - 큰 카드, 모달
Radius XL:  16px  - 주요 컨테이너
Radius Full: 9999px - 원형 (avatar, pill)
```

---

## Shadow (Elevation)

제조 현장의 밝은 조명 고려 - 더 진한 그림자

```
Shadow XS:  0 1px 2px rgba(0, 0, 0, 0.08)           (미세)
Shadow S:   0 2px 4px rgba(0, 0, 0, 0.12)           (기본)
Shadow M:   0 4px 8px rgba(0, 0, 0, 0.15)           (카드 호버)
Shadow L:   0 8px 16px rgba(0, 0, 0, 0.18)          (모달)
Shadow XL:  0 16px 32px rgba(0, 0, 0, 0.2)          (드롭다운)
Shadow Inner: inset 0 2px 4px rgba(0, 0, 0, 0.08)   (눌림)
```

**변경 이유**: 기존보다 불투명도 증가로 밝은 환경에서 구분 명확

---

## 아이콘 시스템

### Icon Size

```
Icon XS:  16px  (인라인 아이콘)
Icon S:   20px  (버튼 아이콘)
Icon M:   24px  (기본 아이콘)
Icon L:   32px  (헤더 아이콘)
Icon XL:  48px  (대시보드 아이콘)
```

### Recommended Icon Set

**Heroicons** (MIT License, Tailwind 팀 제작)
- https://heroicons.com
- Outline/Solid 버전
- SVG 형식

**주요 아이콘:**
```
- document-text      (문서)
- folder             (템플릿, 작업)
- chat-bubble        (채팅)
- photo              (이미지 업로드)
- check-circle       (성공)
- x-circle           (오류)
- exclamation        (경고)
- arrow-path         (재시도)
- cog                (설정)
- user               (검사자)
```

---

## 컴포넌트 (Components)

### Buttons

#### Primary Button
```
Size: 44px 높이 (터치 최적화)
Padding: 12px 24px
Border-radius: 6px
Background: Primary 500
Text: White, Medium 16px
Shadow: Shadow S
Hover: Primary 600 + Shadow M
Active: Primary 700 + Shadow Inner
Disabled: Gray 200 + Gray 400 텍스트
```

#### Secondary Button
```
Background: White
Border: 1.5px solid Gray 300
Text: Gray 700, Medium 16px
Hover: Gray 50 background
```

#### Icon Button
```
Size: 44px × 44px
Padding: 10px
Border-radius: 6px
Background: Gray 100
Icon: 24px, Gray 600
Hover: Gray 200
```

### Input Fields

#### Text Input
```
Height: 44px
Padding: 12px 16px
Border: 1.5px solid Gray 300
Border-radius: 6px
Font: Body M, Gray 700
Placeholder: Gray 400
Focus: Primary 500 border (2px) + Primary 50 background
Error: Error 500 border + Error 50 background
```

#### Select
```
Height: 44px
Padding: 12px 16px
Border: 1.5px solid Gray 300
Border-radius: 6px
Icon: Chevron-down, 20px
```

### Cards

#### Basic Card
```
Background: White
Padding: 24px
Border-radius: 8px
Shadow: Shadow S
Hover: Shadow M + translateY(-2px)
```

#### Status Card (작업 상태)
```
Background: White
Padding: 20px
Border-radius: 8px
Border-left: 4px solid (Status Color)
Shadow: Shadow S

States:
- In Progress: Border Primary 500
- Completed: Border Success 500
- Failed: Border Error 500
- Pending: Border Warning 500
```

### Badges

#### Status Badge
```
Padding: 4px 12px
Border-radius: Full
Font: Caption, Semibold
Background: (Status 100)
Text: (Status 700)

- Success: Success 100 bg + Success 700 text
- Warning: Warning 100 bg + Warning 700 text
- Error: Error 100 bg + Error 700 text
```

### Toast/Alert

#### Success Toast
```
Background: Success 50
Border: 1px solid Success 200
Border-left: 4px solid Success 500
Icon: check-circle, Success 500
Padding: 16px
Border-radius: 8px
```

#### Error Toast
```
Background: Error 50
Border: 1px solid Error 200
Border-left: 4px solid Error 500
Icon: x-circle, Error 500
Padding: 16px
Border-radius: 8px
```

### Modal

```
Backdrop: rgba(0, 0, 0, 0.6)  (더 진하게)
Content:
  Background: White
  Padding: 32px
  Border-radius: 12px
  Shadow: Shadow XL
  Max-width: 600px
```

---

## 레이아웃 (Layout)

### Breakpoints

```
Mobile:    < 640px
Tablet:    640px - 1024px
Desktop:   > 1024px
Wide:      > 1440px
```

### Container

```
Max-width: 1280px  (현재 1200px에서 확장)
Padding:
  Mobile: 16px
  Tablet: 24px
  Desktop: 32px
```

### Grid

```
Columns: 12
Gap: 24px
Margin: Container padding
```

---

## 애니메이션 (Animation)

제조 현장: 빠르고 명확한 피드백

### Duration

```
Instant:  0ms      (즉시)
Fast:     100ms    (호버)
Normal:   200ms    (기본 전환)
Slow:     300ms    (모달, 드로워)
Slower:   500ms    (페이지 전환)
```

### Easing

```
Linear:     linear                          (로딩)
Ease:       ease                            (기본)
Ease-in:    cubic-bezier(0.4, 0, 1, 1)     (사라짐)
Ease-out:   cubic-bezier(0, 0, 0.2, 1)     (나타남)
Ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)  (양방향)
```

### 주요 애니메이션

```css
/* Fade in */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Slide up */
@keyframes slideUp {
  from {
    transform: translateY(10px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

/* Bounce (성공 피드백) */
@keyframes bounce {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}

/* Shake (에러 피드백) */
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}
```

---

## 접근성 (Accessibility)

### Color Contrast

```
Normal Text:  4.5:1 minimum (WCAG AA)
Large Text:   3:1 minimum
UI Elements:  3:1 minimum
```

### Focus State

```
Outline: 2px solid Primary 500
Outline-offset: 2px
Border-radius: 유지
```

### Screen Reader

```
- 모든 아이콘에 aria-label
- 버튼에 명확한 텍스트
- form 요소에 label 연결
- 에러 메시지 aria-live="polite"
```

---

## 다크 모드 (선택사항)

제조 현장: 주로 밝은 환경, 다크 모드는 낮은 우선순위

현재는 라이트 모드에 집중하되, 향후 확장 고려

```
Primary: 더 밝은 shade 사용 (#60a5fa)
Background: Gray 900
Surface: Gray 800
Text: Gray 100
```

---

## Figma 파일 구조 제안

```
📦 File Auto Pipeline Design System
├── 📄 Cover (표지 페이지)
│   └── 프로젝트 소개, 버전, 변경 이력
│
├── 🎨 Foundation (기초)
│   ├── Colors
│   │   ├── Primary Palette
│   │   ├── Status Colors
│   │   ├── Neutral Palette
│   │   └── Semantic Colors
│   ├── Typography
│   │   ├── Font Families
│   │   ├── Type Scale
│   │   ├── Font Weights
│   │   └── Line Heights
│   ├── Spacing
│   │   └── 4px Grid System
│   ├── Elevation
│   │   └── Shadow Tokens
│   └── Icons
│       └── Heroicons Set
│
├── 🧩 Components (컴포넌트)
│   ├── Buttons
│   │   ├── Primary
│   │   ├── Secondary
│   │   ├── Icon Button
│   │   └── States (Hover, Active, Disabled)
│   ├── Inputs
│   │   ├── Text Input
│   │   ├── Select
│   │   ├── Textarea
│   │   └── File Upload
│   ├── Cards
│   │   ├── Basic Card
│   │   ├── Status Card
│   │   └── Action Card
│   ├── Badges
│   │   ├── Status Badge
│   │   └── Count Badge
│   ├── Toast/Alert
│   │   ├── Success
│   │   ├── Warning
│   │   ├── Error
│   │   └── Info
│   ├── Modal
│   │   ├── Modal Backdrop
│   │   ├── Modal Content
│   │   └── Modal Actions
│   ├── Navigation
│   │   ├── Navbar
│   │   ├── Breadcrumb
│   │   └── Tabs
│   └── Data Display
│       ├── Table
│       ├── List Item
│       └── Field Display
│
├── 📐 Patterns (패턴)
│   ├── Form Layouts
│   ├── Data Entry
│   ├── Status Display
│   └── Empty States
│
└── 📱 Pages (페이지)
    ├── Dashboard
    │   ├── Desktop
    │   ├── Tablet
    │   └── Mobile
    ├── Chat
    │   ├── Desktop
    │   ├── Tablet
    │   └── Mobile
    ├── Templates
    │   └── Template List
    ├── Jobs
    │   ├── Job List
    │   └── Job Detail
    └── Extraction Result
        └── Field Review
```

---

## 구현 우선순위

### Phase 1: 핵심 토큰
- [ ] 색상 변수 업데이트
- [ ] 타이포그래피 적용
- [ ] 간격 시스템 표준화

### Phase 2: 기본 컴포넌트
- [ ] Buttons (Primary, Secondary, Icon)
- [ ] Inputs (Text, Select)
- [ ] Cards (Basic, Status)

### Phase 3: 복합 컴포넌트
- [ ] Toast/Alert
- [ ] Modal
- [ ] Navigation

### Phase 4: 페이지 적용
- [ ] Chat 페이지 리디자인
- [ ] Dashboard 페이지
- [ ] Jobs 페이지

---

## 참고 자료

### Design Systems
- [Tailwind CSS](https://tailwindcss.com/docs/customizing-colors) - 색상 팔레트 참고
- [Material Design 3](https://m3.material.io/) - 컴포넌트 패턴
- [Apple HIG](https://developer.apple.com/design/human-interface-guidelines/) - 터치 타겟

### Fonts
- [Pretendard](https://github.com/orioncactus/pretendard) - 한글 폰트
- [JetBrains Mono](https://www.jetbrains.com/lp/mono/) - 모노스페이스

### Icons
- [Heroicons](https://heroicons.com/) - 아이콘 세트

---

**마지막 업데이트:** 2024-12-04
**버전:** 1.0.0
**담당:** Design System Team
