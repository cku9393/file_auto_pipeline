"""
Core layer: 운영 안전 핵심 모듈.

이 모듈만 건드리면 운영사고 → 가장 보수적으로 관리

역할:
- SSOT (job.json), 락, 해시, derived 정규화
"""

from .hashing import compute_packet_full_hash, compute_packet_hash
from .ids import generate_job_id, generate_run_id
from .logging import create_run_log, emit_warning, save_run_log
from .photos import archive_old_derived, safe_move, select_photo_for_slot
from .ssot_job import (
    atomic_write_json,
    ensure_job_json,
    job_lock,
    load_job_json,
    verify_mismatch,
)

__all__ = [
    # ssot_job
    "job_lock",
    "atomic_write_json",
    "verify_mismatch",
    "load_job_json",
    "ensure_job_json",
    # ids
    "generate_job_id",
    "generate_run_id",
    # hashing
    "compute_packet_hash",
    "compute_packet_full_hash",
    # photos
    "safe_move",
    "select_photo_for_slot",
    "archive_old_derived",
    # logging
    "create_run_log",
    "emit_warning",
    "save_run_log",
]
