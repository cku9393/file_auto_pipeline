"""
해시 계산: packet_hash, packet_full_hash

AGENTS.md 규칙:
- packet_hash: 판정 동일성 (free_text 제외)
- packet_full_hash: 변경 감지 (모든 필드 포함)
- 정렬된 키로 직렬화
- SHA-256
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def load_field_types(definition_path: Path) -> dict[str, str]:
    """
    definition.yaml에서 필드별 타입 로드.

    Args:
        definition_path: definition.yaml 경로

    Returns:
        {필드명: 타입} 딕셔너리
    """
    with open(definition_path, encoding="utf-8") as f:
        definition = yaml.safe_load(f)

    return {
        field_name: field_def.get("type", "token")
        for field_name, field_def in definition.get("fields", {}).items()
    }


def get_excluded_fields(
    field_types: dict[str, str],
    exclude_types: list[str],
) -> set[str]:
    """
    제외할 필드명 집합 반환.

    Args:
        field_types: {필드명: 타입}
        exclude_types: 제외할 타입 목록 (예: ["free_text"])

    Returns:
        제외할 필드명 집합
    """
    return {
        field_name
        for field_name, field_type in field_types.items()
        if field_type in exclude_types
    }


def compute_packet_hash(
    data: dict[str, Any],
    config: dict,
    definition_path: Path,
) -> str:
    """
    판정 동일성 해시 계산.

    - free_text 필드 제외 (remark 등)
    - 정렬된 키로 직렬화
    - SHA-256

    Args:
        data: 패킷 데이터
        config: 설정 (hashing.exclude_from_packet_hash 포함)
        definition_path: definition.yaml 경로

    Returns:
        SHA-256 해시 문자열
    """
    # 제외할 타입 목록 (기본값: ["free_text"])
    exclude_types = config.get("hashing", {}).get(
        "exclude_from_packet_hash", ["free_text"]
    )

    field_types = load_field_types(definition_path)
    excluded_fields = get_excluded_fields(field_types, exclude_types)

    # 제외 필드 필터링
    filtered = {k: v for k, v in data.items() if k not in excluded_fields}

    # measurements도 포함하되, 내부 필드 정렬
    if "measurements" in filtered:
        filtered["measurements"] = [
            dict(sorted(m.items())) if isinstance(m, dict) else m
            for m in filtered["measurements"]
        ]

    serialized = json.dumps(filtered, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def compute_packet_full_hash(data: dict[str, Any]) -> str:
    """
    전체 필드 해시 계산 (감사/변경 감지용).

    - 모든 필드 포함 (free_text 포함)
    - 정렬된 키로 직렬화
    - SHA-256

    Args:
        data: 패킷 데이터

    Returns:
        SHA-256 해시 문자열
    """
    # measurements 내부 필드도 정렬
    data_copy = dict(data)
    if "measurements" in data_copy:
        data_copy["measurements"] = [
            dict(sorted(m.items())) if isinstance(m, dict) else m
            for m in data_copy["measurements"]
        ]

    serialized = json.dumps(data_copy, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def compute_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    """
    파일 해시 계산.

    Args:
        file_path: 파일 경로
        algorithm: 해시 알고리즘 (기본: sha256)

    Returns:
        해시 문자열
    """
    h = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
