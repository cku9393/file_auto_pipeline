#!/usr/bin/env python
"""
Generate expected golden files for scenarios.

This script renders documents for each scenario and saves the extracted
content as expected/*.json files.

WARNING: This should only be used to initialize or update golden files.
Generated files should be manually reviewed before committing.
NEVER run this automatically in CI.

Usage:
    python -m src.testing.golden.generate_expected

    # Generate for specific scenario:
    python -m src.testing.golden.generate_expected scenario_001_basic

    # List scenarios without generating:
    python -m src.testing.golden.generate_expected --list
"""

import argparse
import json
import os
import sys
from pathlib import Path


class CIEnvironmentError(RuntimeError):
    """Raised when generate_expected is run in CI environment."""
    pass


def _check_ci_environment() -> None:
    """
    Check if running in a CI environment and block execution.

    Detects common CI environment variables:
    - CI (generic, used by GitHub Actions, GitLab CI, etc.)
    - GITHUB_ACTIONS
    - GITLAB_CI
    - JENKINS_URL
    - CIRCLECI
    - TRAVIS
    - BUILDKITE

    Raises:
        CIEnvironmentError: If CI environment detected
    """
    ci_indicators = [
        "CI",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "JENKINS_URL",
        "CIRCLECI",
        "TRAVIS",
        "BUILDKITE",
        "TF_BUILD",  # Azure Pipelines
        "CODEBUILD_BUILD_ID",  # AWS CodeBuild
    ]

    for indicator in ci_indicators:
        if os.getenv(indicator):
            raise CIEnvironmentError(
                f"ERROR: generate_expected cannot run in CI environment.\n"
                f"Detected CI indicator: {indicator}={os.getenv(indicator)}\n\n"
                f"Expected files must be generated locally and reviewed manually.\n"
                f"This prevents accidental baseline updates that mask real failures.\n\n"
                f"To generate expected files:\n"
                f"  1. Run locally: python -m src.testing.golden.generate_expected\n"
                f"  2. Review the generated JSON files\n"
                f"  3. Commit if changes are intentional"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate expected golden files for scenarios",
        epilog="WARNING: Review generated files before committing!",
    )
    parser.add_argument(
        "scenarios",
        nargs="*",
        help="Specific scenarios to generate (default: all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios without generating",
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        default=None,
        help="Path to golden tests directory",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=None,
        help="Path to templates directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing expected files",
    )

    args = parser.parse_args()

    # Block execution in CI environments (except --list which is read-only)
    if not args.list:
        try:
            _check_ci_environment()
        except CIEnvironmentError as e:
            print(str(e), file=sys.stderr)
            return 1

    # Find project root
    project_root = Path(__file__).parent.parent.parent.parent
    golden_dir = args.golden_dir or project_root / "tests" / "golden"
    templates_dir = args.templates_dir or project_root / "templates"
    output_dir = project_root / "tests" / "golden" / "_output"

    # Import after path setup
    from src.testing.golden.runner import GoldenRunner, discover_scenarios

    # Discover scenarios
    scenarios = discover_scenarios(golden_dir)

    if not scenarios:
        print(f"No scenarios found in {golden_dir}")
        return 1

    # List mode
    if args.list:
        print("Available scenarios:")
        for s in scenarios:
            expected_dir = s.path / "expected"
            has_expected = (expected_dir / "docx.json").exists()
            status = "✓" if has_expected else "○"
            print(f"  {status} {s.name}")
        return 0

    # Filter scenarios if specified
    if args.scenarios:
        scenarios = [s for s in scenarios if s.name in args.scenarios]
        if not scenarios:
            print(f"No matching scenarios found for: {args.scenarios}")
            return 1

    # Create runner with auto template selection
    # This allows scenario_002_with_photos to use with_photos template
    runner = GoldenRunner(
        templates_dir=templates_dir,
        output_dir=output_dir,
        template_id="auto",  # Auto-select based on scenario (photos → with_photos)
    )

    # Generate expected files
    print("=" * 60)
    print("GENERATING GOLDEN EXPECTED FILES")
    print("=" * 60)
    print()
    print("WARNING: Review generated files before committing!")
    print()

    for scenario in scenarios:
        print(f"Generating: {scenario.name}")

        # Check if expected files exist
        expected_dir = scenario.path / "expected"
        docx_exists = (expected_dir / "docx.json").exists()
        xlsx_exists = (expected_dir / "xlsx.json").exists()

        if (docx_exists or xlsx_exists) and not args.force:
            print(f"  ⚠ Expected files exist. Use --force to overwrite.")
            continue

        try:
            docx_path, xlsx_path = runner.generate_expected(scenario)
            print(f"  ✓ Generated: {docx_path.name}, {xlsx_path.name}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue

    print()
    print("=" * 60)
    print("Done. Please review the generated files before committing.")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
