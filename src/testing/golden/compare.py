"""
Golden comparison utilities.

Provides human-readable diff output for golden test failures.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class DiffResult:
    """Result of comparing two structures."""
    match: bool
    path: str = ""
    expected: Any = None
    actual: Any = None
    message: str = ""

    def __str__(self) -> str:
        if self.match:
            return "OK"
        return f"DIFF at '{self.path}': {self.message}\n  Expected: {self.expected!r}\n  Actual:   {self.actual!r}"


def compare_structures(
    expected: Any,
    actual: Any,
    path: str = "",
    ignore_keys: set[str] | None = None,
) -> list[DiffResult]:
    """
    Compare two structures and return list of differences.

    Args:
        expected: Expected value
        actual: Actual value
        path: Current path (for error messages)
        ignore_keys: Keys to ignore in comparison

    Returns:
        List of DiffResult (empty if match)
    """
    ignore_keys = ignore_keys or set()
    diffs: list[DiffResult] = []

    # Type mismatch
    if type(expected) is not type(actual):
        # Allow None vs missing
        if expected is None and actual is None:
            return []
        diffs.append(DiffResult(
            match=False,
            path=path,
            expected=type(expected).__name__,
            actual=type(actual).__name__,
            message="Type mismatch",
        ))
        return diffs

    # Dict comparison
    if isinstance(expected, dict):
        all_keys = set(expected.keys()) | set(actual.keys())
        for key in sorted(all_keys):
            if key in ignore_keys:
                continue

            new_path = f"{path}.{key}" if path else key

            if key not in expected:
                diffs.append(DiffResult(
                    match=False,
                    path=new_path,
                    expected=None,
                    actual=actual[key],
                    message="Unexpected key in actual",
                ))
            elif key not in actual:
                diffs.append(DiffResult(
                    match=False,
                    path=new_path,
                    expected=expected[key],
                    actual=None,
                    message="Missing key in actual",
                ))
            else:
                diffs.extend(compare_structures(
                    expected[key],
                    actual[key],
                    new_path,
                    ignore_keys,
                ))
        return diffs

    # List comparison
    if isinstance(expected, list):
        if len(expected) != len(actual):
            diffs.append(DiffResult(
                match=False,
                path=path,
                expected=len(expected),
                actual=len(actual),
                message="List length mismatch",
            ))
            # Still compare common elements
            min_len = min(len(expected), len(actual))
        else:
            min_len = len(expected)

        for i in range(min_len):
            new_path = f"{path}[{i}]"
            diffs.extend(compare_structures(
                expected[i],
                actual[i],
                new_path,
                ignore_keys,
            ))
        return diffs

    # Value comparison
    if expected != actual:
        diffs.append(DiffResult(
            match=False,
            path=path,
            expected=expected,
            actual=actual,
            message="Value mismatch",
        ))

    return diffs


def format_diff_report(diffs: list[DiffResult], max_diffs: int = 10) -> str:
    """
    Format a list of diffs into a human-readable report.

    Args:
        diffs: List of DiffResult
        max_diffs: Maximum number of diffs to show

    Returns:
        Formatted diff report string
    """
    if not diffs:
        return "No differences found."

    lines = [f"Found {len(diffs)} difference(s):"]
    lines.append("-" * 60)

    for i, diff in enumerate(diffs[:max_diffs]):
        lines.append(f"\n{i+1}. {diff}")

    if len(diffs) > max_diffs:
        lines.append(f"\n... and {len(diffs) - max_diffs} more differences")

    return "\n".join(lines)


def assert_golden_match(
    expected: dict[str, Any],
    actual: dict[str, Any],
    ignore_keys: set[str] | None = None,
) -> None:
    """
    Assert that actual matches expected, with detailed diff on failure.

    Args:
        expected: Expected golden data
        actual: Actual extracted data
        ignore_keys: Keys to ignore in comparison

    Raises:
        AssertionError: With formatted diff report if mismatch
    """
    diffs = compare_structures(expected, actual, ignore_keys=ignore_keys)

    if diffs:
        report = format_diff_report(diffs)
        raise AssertionError(f"Golden comparison failed:\n{report}")
