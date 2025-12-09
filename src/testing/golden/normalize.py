"""
Normalizer for golden test comparisons.

Handles variable elements that would cause false test failures:
- Timestamps → <TS>
- UUIDs → <UUID>
- Excessive whitespace → single space

Includes replacement counting to detect over-normalization.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass
class NormalizationStats:
    """Statistics about normalization replacements."""
    uuid_count: int = 0
    timestamp_count: int = 0
    date_count: int = 0

    def total(self) -> int:
        """Total replacement count."""
        return self.uuid_count + self.timestamp_count + self.date_count

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "UUID": self.uuid_count,
            "TS": self.timestamp_count,
            "DATE": self.date_count,
            "total": self.total(),
        }


class NormalizationWarning(UserWarning):
    """Warning for suspicious normalization patterns."""
    pass


class Normalizer:
    """
    Normalize values for stable golden comparisons.

    Variable elements like timestamps and UUIDs are replaced with
    placeholders to prevent false test failures.

    Tracks replacement counts to detect over-normalization:
    - If too many UUIDs or timestamps are replaced, it may indicate
      that real content is being masked.
    """

    # ISO 8601 timestamp pattern
    TIMESTAMP_PATTERN = re.compile(
        r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'
    )

    # UUID pattern (v4)
    UUID_PATTERN = re.compile(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    )

    # Date patterns (YYYY-MM-DD, YYYY/MM/DD, etc.)
    DATE_PATTERN = re.compile(
        r'\d{4}[-/]\d{2}[-/]\d{2}'
    )

    # Default thresholds for warnings
    DEFAULT_UUID_THRESHOLD = 20
    DEFAULT_TS_THRESHOLD = 20
    DEFAULT_DATE_THRESHOLD = 50

    def __init__(
        self,
        normalize_timestamps: bool = True,
        normalize_uuids: bool = True,
        normalize_whitespace: bool = True,
        normalize_numbers: bool = True,
        exclude_fields: set[str] | None = None,
        uuid_threshold: int | None = None,
        timestamp_threshold: int | None = None,
        date_threshold: int | None = None,
    ):
        """
        Args:
            normalize_timestamps: Replace timestamps with <TS>
            normalize_uuids: Replace UUIDs with <UUID>
            normalize_whitespace: Collapse multiple whitespace to single space
            normalize_numbers: Normalize numeric precision
            exclude_fields: Field names to exclude from comparison
            uuid_threshold: Max UUID replacements before warning (None = default 20)
            timestamp_threshold: Max timestamp replacements before warning (None = default 20)
            date_threshold: Max date replacements before warning (None = default 50)
        """
        self.normalize_timestamps = normalize_timestamps
        self.normalize_uuids = normalize_uuids
        self.normalize_whitespace = normalize_whitespace
        self.normalize_numbers = normalize_numbers
        self.exclude_fields = exclude_fields or set()

        # Thresholds for warnings
        self.uuid_threshold = uuid_threshold if uuid_threshold is not None else self.DEFAULT_UUID_THRESHOLD
        self.timestamp_threshold = timestamp_threshold if timestamp_threshold is not None else self.DEFAULT_TS_THRESHOLD
        self.date_threshold = date_threshold if date_threshold is not None else self.DEFAULT_DATE_THRESHOLD

        # Track replacement counts
        self._stats = NormalizationStats()

    @property
    def stats(self) -> NormalizationStats:
        """Get current normalization statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset replacement counters."""
        self._stats = NormalizationStats()

    def check_thresholds(self) -> list[str]:
        """
        Check if any replacement counts exceed thresholds.

        Returns:
            List of warning messages (empty if all OK)
        """
        warnings = []

        if self._stats.uuid_count > self.uuid_threshold:
            warnings.append(
                f"UUID replacements ({self._stats.uuid_count}) exceed threshold ({self.uuid_threshold}). "
                f"Document may contain abnormally many UUIDs or false positives."
            )

        if self._stats.timestamp_count > self.timestamp_threshold:
            warnings.append(
                f"Timestamp replacements ({self._stats.timestamp_count}) exceed threshold ({self.timestamp_threshold}). "
                f"Document may contain abnormally many timestamps or false positives."
            )

        if self._stats.date_count > self.date_threshold:
            warnings.append(
                f"Date replacements ({self._stats.date_count}) exceed threshold ({self.date_threshold}). "
                f"Document may contain abnormally many dates or false positives."
            )

        return warnings

    def normalize(self, value: Any) -> Any:
        """
        Normalize a value for comparison.

        Args:
            value: Any value to normalize

        Returns:
            Normalized value
        """
        if value is None:
            return None

        if isinstance(value, str):
            return self._normalize_string(value)

        if isinstance(value, (int, float, Decimal)):
            return self._normalize_number(value)

        if isinstance(value, list):
            return [self.normalize(item) for item in value]

        if isinstance(value, dict):
            return {
                k: self.normalize(v)
                for k, v in value.items()
                if k not in self.exclude_fields
            }

        return value

    def _normalize_string(self, text: str) -> str:
        """Normalize a string value."""
        result = text

        # Normalize whitespace first
        if self.normalize_whitespace:
            # Replace various whitespace with regular space
            result = re.sub(r'[\t\r\n]+', ' ', result)
            # Collapse multiple spaces to one
            result = re.sub(r' {2,}', ' ', result)
            # Strip leading/trailing whitespace
            result = result.strip()

        # Replace timestamps (with counting)
        if self.normalize_timestamps:
            ts_matches = len(self.TIMESTAMP_PATTERN.findall(result))
            date_matches = len(self.DATE_PATTERN.findall(result))

            result = self.TIMESTAMP_PATTERN.sub('<TS>', result)
            result = self.DATE_PATTERN.sub('<DATE>', result)

            self._stats.timestamp_count += ts_matches
            self._stats.date_count += date_matches

        # Replace UUIDs (with counting)
        if self.normalize_uuids:
            uuid_matches = len(self.UUID_PATTERN.findall(result))
            result = self.UUID_PATTERN.sub('<UUID>', result)
            self._stats.uuid_count += uuid_matches

        return result

    def _normalize_number(self, value: int | float | Decimal) -> str:
        """
        Normalize a number to string for consistent comparison.

        Prevents issues like 1.0 vs 1.00 or floating point imprecision.
        """
        if not self.normalize_numbers:
            return str(value)

        try:
            # Convert to Decimal for consistent precision
            if isinstance(value, float):
                # Round to avoid floating point artifacts
                dec = Decimal(str(round(value, 10)))
            elif isinstance(value, Decimal):
                dec = value
            else:
                dec = Decimal(value)

            # Normalize: remove trailing zeros
            normalized = dec.normalize()

            # Handle scientific notation edge cases
            if 'E' in str(normalized):
                # Convert back to regular notation if reasonable
                return f"{float(normalized):.10g}"

            return str(normalized)

        except (InvalidOperation, ValueError):
            return str(value)


def normalize_for_comparison(
    data: Any,
    exclude_fields: set[str] | None = None,
) -> Any:
    """
    Convenience function to normalize data for golden comparison.

    Args:
        data: Data structure to normalize
        exclude_fields: Fields to exclude from comparison

    Returns:
        Normalized data
    """
    normalizer = Normalizer(exclude_fields=exclude_fields)
    return normalizer.normalize(data)
