"""
test_hashing.py - 해시 계산 테스트

DoD:
- packet_hash/full_hash 동일 입력 → 동일 해시 (재현성)
- packet_hash는 free_text 제외
- packet_full_hash는 모든 필드 포함
"""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from src.core.hashing import (
    compute_file_hash,
    compute_packet_full_hash,
    compute_packet_hash,
    get_excluded_fields,
    load_field_types,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_definition(tmp_path: Path) -> Path:
    """테스트용 definition.yaml 생성."""
    definition = {
        "definition_version": "1.0.0",
        "fields": {
            "wo_no": {"type": "token", "importance": "critical"},
            "line": {"type": "token", "importance": "critical"},
            "part_no": {"type": "token", "importance": "critical"},
            "result": {"type": "token", "importance": "critical"},
            "inspector": {"type": "token", "importance": "reference"},
            "remark": {"type": "free_text", "importance": "reference"},
            "notes": {"type": "free_text", "importance": "optional"},
        },
    }

    definition_path = tmp_path / "definition.yaml"
    with open(definition_path, "w", encoding="utf-8") as f:
        yaml.dump(definition, f, allow_unicode=True)

    return definition_path


@pytest.fixture
def hash_config() -> dict:
    """해시 관련 설정."""
    return {
        "hashing": {
            "exclude_from_packet_hash": ["free_text"],
        },
    }


# =============================================================================
# load_field_types 테스트
# =============================================================================

class TestLoadFieldTypes:
    """load_field_types 함수 테스트."""

    def test_loads_field_types(self, sample_definition: Path):
        """필드 타입 정상 로드."""
        field_types = load_field_types(sample_definition)

        assert field_types["wo_no"] == "token"
        assert field_types["remark"] == "free_text"
        assert field_types["notes"] == "free_text"

    def test_default_type_token(self, tmp_path: Path):
        """타입 미지정 시 기본값 token."""
        definition = {
            "fields": {
                "some_field": {},  # 타입 없음
            },
        }
        definition_path = tmp_path / "definition.yaml"
        with open(definition_path, "w") as f:
            yaml.dump(definition, f)

        field_types = load_field_types(definition_path)

        assert field_types["some_field"] == "token"


# =============================================================================
# get_excluded_fields 테스트
# =============================================================================

class TestGetExcludedFields:
    """get_excluded_fields 함수 테스트."""

    def test_excludes_free_text(self):
        """free_text 타입 필드 제외."""
        field_types = {
            "wo_no": "token",
            "remark": "free_text",
            "notes": "free_text",
        }

        excluded = get_excluded_fields(field_types, ["free_text"])

        assert excluded == {"remark", "notes"}

    def test_multiple_exclude_types(self):
        """여러 타입 제외."""
        field_types = {
            "a": "token",
            "b": "free_text",
            "c": "optional",
        }

        excluded = get_excluded_fields(field_types, ["free_text", "optional"])

        assert excluded == {"b", "c"}


# =============================================================================
# compute_packet_hash 테스트 (재현성)
# =============================================================================

class TestComputePacketHash:
    """compute_packet_hash 함수 테스트."""

    def test_same_input_same_hash(self, sample_definition: Path, hash_config: dict):
        """동일 입력 → 동일 해시 (재현성)."""
        data = {
            "wo_no": "WO-001",
            "line": "L1",
            "part_no": "PART-A",
            "result": "PASS",
        }

        hash_1 = compute_packet_hash(data, hash_config, sample_definition)
        hash_2 = compute_packet_hash(data, hash_config, sample_definition)

        assert hash_1 == hash_2

    def test_excludes_free_text_fields(
        self, sample_definition: Path, hash_config: dict
    ):
        """free_text 필드 제외 확인."""
        data_1 = {
            "wo_no": "WO-001",
            "line": "L1",
            "remark": "비고 1",  # free_text
        }

        data_2 = {
            "wo_no": "WO-001",
            "line": "L1",
            "remark": "비고 2 (다른 내용)",  # free_text 변경
        }

        hash_1 = compute_packet_hash(data_1, hash_config, sample_definition)
        hash_2 = compute_packet_hash(data_2, hash_config, sample_definition)

        # remark가 달라도 해시 동일 (free_text 제외)
        assert hash_1 == hash_2

    def test_different_critical_fields_different_hash(
        self, sample_definition: Path, hash_config: dict
    ):
        """critical 필드 변경 시 해시 다름."""
        data_1 = {"wo_no": "WO-001", "line": "L1"}
        data_2 = {"wo_no": "WO-002", "line": "L1"}  # wo_no 다름

        hash_1 = compute_packet_hash(data_1, hash_config, sample_definition)
        hash_2 = compute_packet_hash(data_2, hash_config, sample_definition)

        assert hash_1 != hash_2

    def test_key_order_independence(self, sample_definition: Path, hash_config: dict):
        """키 순서와 무관하게 동일 해시."""
        data_1 = {"wo_no": "WO-001", "line": "L1", "part_no": "P1"}
        data_2 = {"part_no": "P1", "wo_no": "WO-001", "line": "L1"}  # 순서 다름

        hash_1 = compute_packet_hash(data_1, hash_config, sample_definition)
        hash_2 = compute_packet_hash(data_2, hash_config, sample_definition)

        assert hash_1 == hash_2

    def test_measurements_included(self, sample_definition: Path, hash_config: dict):
        """measurements 포함."""
        data_1 = {
            "wo_no": "WO-001",
            "measurements": [
                {"item": "길이", "measured": "10.0"},
            ],
        }

        data_2 = {
            "wo_no": "WO-001",
            "measurements": [
                {"item": "길이", "measured": "10.5"},  # 값 다름
            ],
        }

        hash_1 = compute_packet_hash(data_1, hash_config, sample_definition)
        hash_2 = compute_packet_hash(data_2, hash_config, sample_definition)

        # measurements 변경 시 해시 다름
        assert hash_1 != hash_2

    def test_measurements_order_independence(
        self, sample_definition: Path, hash_config: dict
    ):
        """measurements 내부 키 순서와 무관."""
        data_1 = {
            "wo_no": "WO-001",
            "measurements": [{"item": "길이", "measured": "10.0"}],
        }

        data_2 = {
            "wo_no": "WO-001",
            "measurements": [{"measured": "10.0", "item": "길이"}],  # 키 순서 다름
        }

        hash_1 = compute_packet_hash(data_1, hash_config, sample_definition)
        hash_2 = compute_packet_hash(data_2, hash_config, sample_definition)

        assert hash_1 == hash_2

    def test_returns_sha256_hex(self, sample_definition: Path, hash_config: dict):
        """SHA-256 hex 문자열 반환."""
        data = {"wo_no": "WO-001"}

        result = compute_packet_hash(data, hash_config, sample_definition)

        # SHA-256 = 64자리 hex
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


# =============================================================================
# compute_packet_full_hash 테스트
# =============================================================================

class TestComputePacketFullHash:
    """compute_packet_full_hash 함수 테스트."""

    def test_same_input_same_hash(self):
        """동일 입력 → 동일 해시."""
        data = {"wo_no": "WO-001", "remark": "비고"}

        hash_1 = compute_packet_full_hash(data)
        hash_2 = compute_packet_full_hash(data)

        assert hash_1 == hash_2

    def test_includes_all_fields(self):
        """모든 필드 포함 (free_text 포함)."""
        data_1 = {"wo_no": "WO-001", "remark": "비고 1"}
        data_2 = {"wo_no": "WO-001", "remark": "비고 2"}

        hash_1 = compute_packet_full_hash(data_1)
        hash_2 = compute_packet_full_hash(data_2)

        # remark가 다르면 full_hash도 다름
        assert hash_1 != hash_2

    def test_key_order_independence(self):
        """키 순서와 무관."""
        data_1 = {"a": "1", "b": "2", "c": "3"}
        data_2 = {"c": "3", "a": "1", "b": "2"}

        hash_1 = compute_packet_full_hash(data_1)
        hash_2 = compute_packet_full_hash(data_2)

        assert hash_1 == hash_2


# =============================================================================
# compute_file_hash 테스트
# =============================================================================

class TestComputeFileHash:
    """compute_file_hash 함수 테스트."""

    def test_same_file_same_hash(self, tmp_path: Path):
        """동일 파일 → 동일 해시."""
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(b"test content")

        hash_1 = compute_file_hash(file_path)
        hash_2 = compute_file_hash(file_path)

        assert hash_1 == hash_2

    def test_different_content_different_hash(self, tmp_path: Path):
        """다른 내용 → 다른 해시."""
        file_1 = tmp_path / "file1.txt"
        file_2 = tmp_path / "file2.txt"
        file_1.write_bytes(b"content 1")
        file_2.write_bytes(b"content 2")

        hash_1 = compute_file_hash(file_1)
        hash_2 = compute_file_hash(file_2)

        assert hash_1 != hash_2

    def test_matches_expected_sha256(self, tmp_path: Path):
        """예상 SHA-256과 일치."""
        file_path = tmp_path / "test.txt"
        content = b"hello world"
        file_path.write_bytes(content)

        result = compute_file_hash(file_path)

        # 직접 계산한 해시와 비교
        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_different_algorithm(self, tmp_path: Path):
        """다른 알고리즘 사용."""
        file_path = tmp_path / "test.txt"
        content = b"hello"
        file_path.write_bytes(content)

        sha256_hash = compute_file_hash(file_path, algorithm="sha256")
        md5_hash = compute_file_hash(file_path, algorithm="md5")

        # 다른 알고리즘 = 다른 결과
        assert sha256_hash != md5_hash
        assert len(md5_hash) == 32  # MD5 = 32자리
