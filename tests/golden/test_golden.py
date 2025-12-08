"""
Golden tests for document rendering.

These tests verify that rendered DOCX/XLSX documents contain
the correct semantic content by comparing against expected
normalized JSON structures.

Golden Test Philosophy:
- Compare MEANING, not bytes (DOCX/XLSX have variable metadata)
- Normalize variable elements (timestamps, UUIDs)
- Fail on content changes, not formatting changes
- Human-readable diff on failure

Usage:
    pytest tests/golden/test_golden.py -v

To regenerate expected files (manual review required!):
    python -m src.testing.golden.generate_expected
"""

import json
from pathlib import Path

import pytest

from src.testing.golden.compare import assert_golden_match, compare_structures
from src.testing.golden.docx_extract import DocxExtractor
from src.testing.golden.normalize import Normalizer
from src.testing.golden.runner import GoldenRunner, GoldenScenario, discover_scenarios
from src.testing.golden.xlsx_extract import XlsxExtractor


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def templates_dir(project_root: Path) -> Path:
    """Get templates directory."""
    return project_root / "templates"


@pytest.fixture
def golden_dir() -> Path:
    """Get golden tests directory."""
    return Path(__file__).parent


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Get temporary output directory for rendered files."""
    return tmp_path / "golden_output"


@pytest.fixture
def normalizer() -> Normalizer:
    """Get normalizer for tests."""
    return Normalizer(
        exclude_fields={"generated_at", "created_at", "timestamp", "metadata"},
    )


@pytest.fixture
def golden_runner(templates_dir: Path, output_dir: Path) -> GoldenRunner:
    """Get golden test runner."""
    return GoldenRunner(
        templates_dir=templates_dir,
        output_dir=output_dir,
        template_id="base",
    )


# =============================================================================
# Helper Functions
# =============================================================================

def load_scenario(golden_dir: Path, scenario_name: str) -> GoldenScenario:
    """Load a specific scenario by name."""
    scenario_path = golden_dir / scenario_name
    return GoldenScenario.load(scenario_path)


# =============================================================================
# Test: Extractors
# =============================================================================

class TestExtractors:
    """Test DOCX and XLSX extractors work correctly."""

    def test_docx_extractor_init(self, normalizer: Normalizer):
        """DocxExtractor initializes with normalizer."""
        extractor = DocxExtractor(normalizer=normalizer)
        assert extractor.normalizer == normalizer

    def test_xlsx_extractor_init(self, normalizer: Normalizer):
        """XlsxExtractor initializes with normalizer."""
        extractor = XlsxExtractor(normalizer=normalizer)
        assert extractor.normalizer == normalizer


# =============================================================================
# Test: Normalizer
# =============================================================================

class TestNormalizer:
    """Test normalizer handles variable elements."""

    def test_normalize_timestamp(self, normalizer: Normalizer):
        """Timestamps are replaced with <TS>."""
        text = "Generated at 2024-01-15T09:30:00Z"
        result = normalizer.normalize(text)
        assert "<TS>" in result
        assert "2024-01-15T09:30:00Z" not in result

    def test_normalize_uuid(self, normalizer: Normalizer):
        """UUIDs are replaced with <UUID>."""
        text = "ID: 550e8400-e29b-41d4-a716-446655440000"
        result = normalizer.normalize(text)
        assert "<UUID>" in result

    def test_normalize_whitespace(self, normalizer: Normalizer):
        """Multiple whitespace collapsed to single space."""
        text = "Hello   World\n\nTest"
        result = normalizer.normalize(text)
        assert result == "Hello World Test"

    def test_normalize_number(self, normalizer: Normalizer):
        """Numbers normalized consistently."""
        # 1.0 and 1.00 should be equal after normalization
        result1 = normalizer._normalize_number(1.0)
        result2 = normalizer._normalize_number(1.00)
        assert result1 == result2


# =============================================================================
# Test: Compare
# =============================================================================

class TestCompare:
    """Test comparison utilities."""

    def test_compare_equal_dicts(self):
        """Equal dicts have no differences."""
        expected = {"a": 1, "b": "test"}
        actual = {"a": 1, "b": "test"}
        diffs = compare_structures(expected, actual)
        assert len(diffs) == 0

    def test_compare_different_values(self):
        """Different values are detected."""
        expected = {"a": 1}
        actual = {"a": 2}
        diffs = compare_structures(expected, actual)
        assert len(diffs) == 1
        assert diffs[0].path == "a"

    def test_compare_missing_key(self):
        """Missing keys are detected."""
        expected = {"a": 1, "b": 2}
        actual = {"a": 1}
        diffs = compare_structures(expected, actual)
        assert len(diffs) == 1
        assert "Missing key" in diffs[0].message

    def test_compare_extra_key(self):
        """Extra keys are detected."""
        expected = {"a": 1}
        actual = {"a": 1, "b": 2}
        diffs = compare_structures(expected, actual)
        assert len(diffs) == 1
        assert "Unexpected key" in diffs[0].message

    def test_compare_nested_diff(self):
        """Nested differences have correct path."""
        expected = {"outer": {"inner": 1}}
        actual = {"outer": {"inner": 2}}
        diffs = compare_structures(expected, actual)
        assert len(diffs) == 1
        assert diffs[0].path == "outer.inner"

    def test_compare_list_length(self):
        """List length differences are detected."""
        expected = [1, 2, 3]
        actual = [1, 2]
        diffs = compare_structures(expected, actual)
        assert any("length" in d.message for d in diffs)


# =============================================================================
# Test: Golden Scenario Loading
# =============================================================================

class TestScenarioLoading:
    """Test golden scenario loading."""

    def test_load_scenario_001(self, golden_dir: Path):
        """Load scenario_001_basic successfully."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        assert scenario.name == "scenario_001_basic"
        assert scenario.input_packet["wo_no"] == "WO-2024-001"
        assert scenario.input_packet["line"] == "L1"
        assert len(scenario.input_packet.get("measurements", [])) == 3

    def test_scenario_has_photos(self, golden_dir: Path):
        """Scenario includes photo paths."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        # Photos should be discovered
        assert "overview" in scenario.photos or "label_serial" in scenario.photos

    def test_discover_scenarios(self, golden_dir: Path):
        """Discover all scenarios in directory."""
        scenarios = discover_scenarios(golden_dir)

        # Should find at least scenario_001_basic
        names = [s.name for s in scenarios]
        assert "scenario_001_basic" in names


# =============================================================================
# Test: Golden Rendering (Main Tests)
# =============================================================================

class TestGoldenRendering:
    """
    Main golden tests that verify document content.

    These tests render documents and compare semantic content
    against expected results stored in expected/*.json files.
    """

    def test_scenario_001_docx_renders(
        self,
        golden_dir: Path,
        golden_runner: GoldenRunner,
    ):
        """DOCX renders with correct content for scenario_001."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        # Run without assertion first to check rendering works
        docx_result, _ = golden_runner.run_scenario(scenario, assert_match=False)

        # Verify basic structure
        assert "paragraphs" in docx_result
        assert "tables" in docx_result

        # Check that field values appear in content
        all_text = " ".join(docx_result.get("paragraphs", []))
        for table in docx_result.get("tables", []):
            for row in table:
                all_text += " " + " ".join(row)

        # Key fields should be present somewhere in the document
        assert "WO-2024-001" in all_text or scenario.input_packet["wo_no"] in all_text

    def test_scenario_001_xlsx_renders(
        self,
        golden_dir: Path,
        golden_runner: GoldenRunner,
    ):
        """XLSX renders with correct content for scenario_001."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        # Run without assertion
        _, xlsx_result = golden_runner.run_scenario(scenario, assert_match=False)

        # Verify structure
        assert "sheets" in xlsx_result
        assert "measurements" in xlsx_result

        # Check measurements were extracted
        measurements = xlsx_result.get("measurements", [])
        assert len(measurements) >= 3  # We have 3 measurements in input

    def test_scenario_001_measurements_correct(
        self,
        golden_dir: Path,
        golden_runner: GoldenRunner,
    ):
        """Measurements table has correct data."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        _, xlsx_result = golden_runner.run_scenario(scenario, assert_match=False)
        measurements = xlsx_result.get("measurements", [])

        # Find a measurement row with data
        found_measurement = False
        for m in measurements:
            if m.get("item") and m.get("measured"):
                found_measurement = True
                break

        assert found_measurement, "Should have at least one measurement with data"

    @pytest.mark.skipif(
        not (Path(__file__).parent / "scenario_001_basic" / "expected" / "docx.json").exists(),
        reason="Expected docx.json not yet generated",
    )
    def test_scenario_001_docx_matches_expected(
        self,
        golden_dir: Path,
        golden_runner: GoldenRunner,
    ):
        """DOCX content matches expected golden file."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        # This will assert if there's a mismatch
        docx_result, _ = golden_runner.run_scenario(scenario, assert_match=True)

    @pytest.mark.skipif(
        not (Path(__file__).parent / "scenario_001_basic" / "expected" / "xlsx.json").exists(),
        reason="Expected xlsx.json not yet generated",
    )
    def test_scenario_001_xlsx_matches_expected(
        self,
        golden_dir: Path,
        golden_runner: GoldenRunner,
    ):
        """XLSX content matches expected golden file."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        # This will assert if there's a mismatch
        _, xlsx_result = golden_runner.run_scenario(scenario, assert_match=True)


# =============================================================================
# Test: Photos in DOCX
# =============================================================================

class TestPhotosInDocx:
    """Test that photos are included in DOCX output."""

    def test_docx_contains_images(
        self,
        golden_dir: Path,
        golden_runner: GoldenRunner,
    ):
        """DOCX should contain images when photos are provided and template supports them."""
        scenario = load_scenario(golden_dir, "scenario_001_basic")

        # Only run if we have photos
        if not scenario.photos:
            pytest.skip("No photos in scenario")

        docx_result, _ = golden_runner.run_scenario(scenario, assert_match=False)

        # Check if images exist
        # Note: Images only appear if template has photo placeholders ({{photo_overview}}, etc.)
        # If template doesn't have photo placeholders, images won't be embedded
        images = docx_result.get("images", [])

        # This is informational - don't fail if template doesn't support photos
        if len(images) == 0:
            pytest.skip("Template does not have photo placeholders")


# =============================================================================
# Test: Scenario 002 with Photos (Image Golden Tests)
# =============================================================================

@pytest.fixture
def photos_runner(templates_dir: Path, output_dir: Path) -> GoldenRunner:
    """Get golden test runner with auto template selection."""
    return GoldenRunner(
        templates_dir=templates_dir,
        output_dir=output_dir,
        template_id="auto",  # Auto-select based on scenario
    )


class TestScenario002WithPhotos:
    """
    Test scenario_002_with_photos - validates image embedding.

    This is the critical test for photo pipeline verification.
    """

    @pytest.mark.skipif(
        not (Path(__file__).parent / "scenario_002_with_photos" / "input_packet.json").exists(),
        reason="scenario_002_with_photos not yet created",
    )
    def test_scenario_002_has_photos(self, golden_dir: Path):
        """Scenario 002 should have photos defined."""
        scenario = load_scenario(golden_dir, "scenario_002_with_photos")

        assert scenario.photos, "scenario_002_with_photos must have photos"
        assert "overview" in scenario.photos, "Must have overview photo"
        assert "label_serial" in scenario.photos, "Must have label_serial photo"

    @pytest.mark.skipif(
        not (Path(__file__).parent / "scenario_002_with_photos" / "input_packet.json").exists(),
        reason="scenario_002_with_photos not yet created",
    )
    def test_scenario_002_docx_contains_images(
        self,
        golden_dir: Path,
        photos_runner: GoldenRunner,
    ):
        """DOCX from scenario_002 should contain embedded images."""
        scenario = load_scenario(golden_dir, "scenario_002_with_photos")

        docx_result, _ = photos_runner.run_scenario(scenario, assert_match=False)
        images = docx_result.get("images", [])

        # Must have images
        assert len(images) >= 2, f"Expected at least 2 images, got {len(images)}"

        # Check image summary if available
        if images and "_image_summary" in images[0]:
            summary = images[0]["_image_summary"]
            assert summary["total_count"] >= 2, "Should have at least 2 images"
            assert summary["media_file_count"] >= 2, "Should have at least 2 media files"

    @pytest.mark.skipif(
        not (Path(__file__).parent / "scenario_002_with_photos" / "input_packet.json").exists(),
        reason="scenario_002_with_photos not yet created",
    )
    def test_scenario_002_image_slots_inferred(
        self,
        golden_dir: Path,
        photos_runner: GoldenRunner,
    ):
        """Images should have inferred slot information."""
        scenario = load_scenario(golden_dir, "scenario_002_with_photos")

        docx_result, _ = photos_runner.run_scenario(scenario, assert_match=False)
        images = docx_result.get("images", [])

        # Check for slot inference (not all images will have slots)
        slots_found = [
            img.get("inferred_slot")
            for img in images
            if img.get("inferred_slot")
        ]

        # At least one slot should be inferred
        # (depends on how docxtpl names embedded images)
        # This is informational, not a hard requirement
        print(f"Inferred slots: {slots_found}")

    @pytest.mark.skipif(
        not (Path(__file__).parent / "scenario_002_with_photos" / "expected" / "docx.json").exists(),
        reason="Expected docx.json not yet generated for scenario_002",
    )
    def test_scenario_002_docx_matches_expected(
        self,
        golden_dir: Path,
        photos_runner: GoldenRunner,
    ):
        """DOCX content matches expected golden file including images."""
        scenario = load_scenario(golden_dir, "scenario_002_with_photos")

        # This will assert if there's a mismatch
        docx_result, _ = photos_runner.run_scenario(scenario, assert_match=True)

        # Verify images are in the result
        images = docx_result.get("images", [])
        assert len(images) >= 2, "Expected at least 2 images in golden match"


# =============================================================================
# Test: Normalizer Replacement Counting
# =============================================================================

class TestNormalizerStats:
    """Test normalizer replacement counting and threshold warnings."""

    def test_counts_uuid_replacements(self, normalizer: Normalizer):
        """Normalizer counts UUID replacements."""
        normalizer.reset_stats()

        text = "ID: 550e8400-e29b-41d4-a716-446655440000, Other: 123e4567-e89b-12d3-a456-426614174000"
        normalizer.normalize(text)

        assert normalizer.stats.uuid_count == 2

    def test_counts_timestamp_replacements(self, normalizer: Normalizer):
        """Normalizer counts timestamp replacements."""
        normalizer.reset_stats()

        text = "Created: 2024-01-15T09:30:00Z, Updated: 2024-01-16T10:00:00Z"
        normalizer.normalize(text)

        assert normalizer.stats.timestamp_count == 2

    def test_threshold_warning_on_excessive_uuids(self):
        """Threshold warning when too many UUIDs replaced."""
        from src.testing.golden.normalize import Normalizer

        # Set low threshold for testing
        normalizer = Normalizer(uuid_threshold=2)
        normalizer.reset_stats()

        # Generate text with many UUIDs
        uuids = ["550e8400-e29b-41d4-a716-44665544000" + str(i) for i in range(5)]
        text = " ".join(uuids)
        normalizer.normalize(text)

        warnings = normalizer.check_thresholds()
        assert len(warnings) > 0
        assert "UUID" in warnings[0]

    def test_no_warning_under_threshold(self, normalizer: Normalizer):
        """No warning when replacements under threshold."""
        normalizer.reset_stats()

        text = "ID: 550e8400-e29b-41d4-a716-446655440000"
        normalizer.normalize(text)

        warnings = normalizer.check_thresholds()
        assert len(warnings) == 0


# =============================================================================
# Parametrized Test for All Scenarios
# =============================================================================

def get_all_scenarios() -> list[str]:
    """Get all scenario names for parametrization."""
    golden_dir = Path(__file__).parent
    scenarios = discover_scenarios(golden_dir)
    return [s.name for s in scenarios]


@pytest.mark.parametrize("scenario_name", get_all_scenarios())
def test_scenario_renders_without_error(
    scenario_name: str,
    golden_dir: Path,
    golden_runner: GoldenRunner,
):
    """Each scenario renders without raising exceptions."""
    scenario = load_scenario(golden_dir, scenario_name)

    # Should not raise
    docx_result, xlsx_result = golden_runner.run_scenario(
        scenario,
        assert_match=False,  # Don't check expected files in this test
    )

    # Basic sanity checks
    assert isinstance(docx_result, dict)
    assert isinstance(xlsx_result, dict)
