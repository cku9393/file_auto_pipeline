"""
test_ids.py - ID 생성 테스트

DoD:
- job_id 결정론적: 동일 packet → 동일 job_id
- run_id 고유성: 매 호출 시 다른 값
- ID 포맷 검증
"""

import re
from datetime import UTC, datetime

from src.core.ids import (
    _sanitize_for_id,
    generate_job_id,
    generate_run_id,
)

# =============================================================================
# generate_job_id 테스트
# =============================================================================


class TestGenerateJobId:
    """generate_job_id 함수 테스트."""

    def test_deterministic_same_input_same_output(self):
        """동일 packet → 동일 job_id (재현성)."""
        packet = {"wo_no": "WO-001", "line": "L1"}

        job_id_1 = generate_job_id(packet)
        job_id_2 = generate_job_id(packet)

        assert job_id_1 == job_id_2

    def test_different_input_different_output(self):
        """다른 packet → 다른 job_id."""
        packet_1 = {"wo_no": "WO-001", "line": "L1"}
        packet_2 = {"wo_no": "WO-001", "line": "L2"}

        job_id_1 = generate_job_id(packet_1)
        job_id_2 = generate_job_id(packet_2)

        assert job_id_1 != job_id_2

    def test_format_prefix(self):
        """JOB- 접두어 확인."""
        packet = {"wo_no": "WO-001", "line": "L1"}

        job_id = generate_job_id(packet)

        assert job_id.startswith("JOB-")

    def test_format_contains_wo_and_line(self):
        """job_id에 wo_no와 line 포함."""
        packet = {"wo_no": "WO001", "line": "L1"}

        job_id = generate_job_id(packet)

        assert "WO001" in job_id
        assert "L1" in job_id

    def test_hash_suffix(self):
        """8자리 해시 suffix 포함."""
        packet = {"wo_no": "WO-001", "line": "L1"}

        job_id = generate_job_id(packet)

        # 포맷: JOB-{wo_no}-{line}-{hash[:8]}
        parts = job_id.split("-")
        last_part = parts[-1]

        # 해시는 8자리 hex
        assert len(last_part) == 8
        assert re.match(r"^[0-9a-f]{8}$", last_part)

    def test_special_characters_sanitized(self):
        """특수문자 정리됨."""
        packet = {"wo_no": "WO/001 TEST", "line": "L-1"}

        job_id = generate_job_id(packet)

        # 슬래시, 공백 등 제거됨
        assert "/" not in job_id
        # 파일명으로 사용 가능
        assert all(c.isalnum() or c in "-_" for c in job_id)

    def test_missing_fields_handled(self):
        """필드 누락 시에도 동작."""
        packet = {}

        job_id = generate_job_id(packet)

        # UNKNOWN 처리됨
        assert "UNKNOWN" in job_id

    def test_unicode_handled(self):
        """한글 등 유니코드 처리."""
        packet = {"wo_no": "작업번호123", "line": "라인A"}

        job_id = generate_job_id(packet)

        # 에러 없이 생성
        assert job_id.startswith("JOB-")
        # ASCII로 사용 가능
        assert all(ord(c) < 128 for c in job_id)


# =============================================================================
# generate_run_id 테스트
# =============================================================================


class TestGenerateRunId:
    """generate_run_id 함수 테스트."""

    def test_unique_each_call(self):
        """매 호출 시 다른 값."""
        run_ids = set()
        for _ in range(100):
            run_ids.add(generate_run_id())

        # 100개 모두 고유
        assert len(run_ids) == 100

    def test_format_prefix(self):
        """RUN- 접두어 확인."""
        run_id = generate_run_id()

        assert run_id.startswith("RUN-")

    def test_contains_timestamp(self):
        """타임스탬프 포함."""
        # generate_run_id는 UTC 사용
        before = datetime.now(UTC)
        run_id = generate_run_id()
        after = datetime.now(UTC)

        # 포맷: RUN-{timestamp}-{uuid}
        parts = run_id.split("-")
        # RUN-20240115123456-abcd1234
        timestamp_part = parts[1]

        # 14자리 타임스탬프 (YYYYMMDDHHmmss)
        assert len(timestamp_part) == 14
        assert timestamp_part.isdigit()

        # 타임스탬프가 before~after 범위 내 (UTC 기준)
        run_time = datetime.strptime(timestamp_part, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        assert before.replace(microsecond=0) <= run_time <= after.replace(microsecond=0)

    def test_safe_for_filename(self):
        """파일명으로 사용 가능."""
        run_id = generate_run_id()

        # 파일명 안전 문자만 포함
        assert all(c.isalnum() or c == "-" for c in run_id)


# =============================================================================
# _sanitize_for_id 테스트
# =============================================================================


class TestSanitizeForId:
    """_sanitize_for_id 헬퍼 함수 테스트."""

    def test_alphanumeric_preserved(self):
        """알파벳/숫자 유지."""
        assert _sanitize_for_id("ABC123") == "ABC123"

    def test_spaces_to_underscore(self):
        """공백 → 밑줄."""
        assert _sanitize_for_id("hello world") == "hello_world"

    def test_special_chars_removed(self):
        """특수문자 제거."""
        assert _sanitize_for_id("a/b:c@d") == "abcd"

    def test_consecutive_underscores_collapsed(self):
        """연속 밑줄 합침."""
        assert _sanitize_for_id("a  b___c") == "a_b_c"

    def test_leading_trailing_underscores_removed(self):
        """앞뒤 밑줄 제거."""
        assert _sanitize_for_id("_abc_") == "abc"

    def test_max_length_20(self):
        """최대 20자 제한."""
        long_string = "a" * 50
        result = _sanitize_for_id(long_string)
        assert len(result) == 20

    def test_empty_returns_unknown(self):
        """빈 문자열 → UNKNOWN."""
        assert _sanitize_for_id("") == "UNKNOWN"
        assert _sanitize_for_id("@#$%") == "UNKNOWN"
