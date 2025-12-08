"""
Golden test utilities for semantic comparison of rendered documents.

This module provides extractors that convert DOCX/XLSX files to normalized
JSON structures for semantic comparison, avoiding brittle binary diffs.

Philosophy:
- Compare MEANING, not bytes
- Normalize variable elements (timestamps, UUIDs)
- Fail on content changes, not formatting changes

Safety Features:
- Replacement counting to detect over-normalization
- CI environment guard to prevent accidental baseline updates
- Header-based XLSX extraction for template resilience
"""

from .compare import assert_golden_match, compare_structures
from .docx_extract import DocxExtractor, extract_docx
from .normalize import NormalizationStats, NormalizationWarning, Normalizer
from .runner import GoldenRunner, GoldenScenario, discover_scenarios
from .xlsx_extract import XlsxExtractor, extract_xlsx

__all__ = [
    # Extractors
    "DocxExtractor",
    "XlsxExtractor",
    "extract_docx",
    "extract_xlsx",
    # Normalization
    "Normalizer",
    "NormalizationStats",
    "NormalizationWarning",
    # Comparison
    "assert_golden_match",
    "compare_structures",
    # Runner
    "GoldenRunner",
    "GoldenScenario",
    "discover_scenarios",
]
