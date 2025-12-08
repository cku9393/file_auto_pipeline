"""
Golden test runner.

Loads scenarios, renders documents, extracts content, and compares with expected results.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.domain.constants import OUTPUT_DOCX_FILENAME, OUTPUT_XLSX_FILENAME

from .compare import assert_golden_match, compare_structures, format_diff_report
from .docx_extract import DocxExtractor
from .normalize import Normalizer
from .xlsx_extract import XlsxExtractor


@dataclass
class GoldenScenario:
    """A golden test scenario."""
    name: str
    path: Path
    input_packet: dict[str, Any]
    overrides: dict[str, Any] = field(default_factory=dict)
    photos: dict[str, Path] = field(default_factory=dict)
    expected_docx: dict[str, Any] | None = None
    expected_xlsx: dict[str, Any] | None = None

    @classmethod
    def load(cls, scenario_path: Path) -> "GoldenScenario":
        """
        Load a scenario from a directory.

        Expected structure:
            scenario_path/
                input_packet.json
                overrides.json (optional)
                photos/ (optional)
                    overview.jpg
                    label_serial.jpg
                expected/
                    docx.json
                    xlsx.json
        """
        name = scenario_path.name

        # Load input packet
        input_packet_path = scenario_path / "input_packet.json"
        if not input_packet_path.exists():
            raise FileNotFoundError(f"Missing input_packet.json in {scenario_path}")

        with open(input_packet_path, encoding="utf-8") as f:
            input_packet = json.load(f)

        # Load overrides (optional)
        overrides: dict[str, Any] = {}
        overrides_path = scenario_path / "overrides.json"
        if overrides_path.exists():
            with open(overrides_path, encoding="utf-8") as f:
                overrides = json.load(f)

        # Find photos
        photos: dict[str, Path] = {}
        photos_dir = scenario_path / "photos"
        if photos_dir.exists():
            for photo_file in photos_dir.iterdir():
                if photo_file.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                    # Use stem as slot key (e.g., "overview.jpg" → "overview")
                    slot_key = photo_file.stem
                    photos[slot_key] = photo_file

        # Load expected results
        expected_dir = scenario_path / "expected"
        expected_docx = None
        expected_xlsx = None

        if expected_dir.exists():
            docx_expected_path = expected_dir / "docx.json"
            if docx_expected_path.exists():
                with open(docx_expected_path, encoding="utf-8") as f:
                    expected_docx = json.load(f)

            xlsx_expected_path = expected_dir / "xlsx.json"
            if xlsx_expected_path.exists():
                with open(xlsx_expected_path, encoding="utf-8") as f:
                    expected_xlsx = json.load(f)

        return cls(
            name=name,
            path=scenario_path,
            input_packet=input_packet,
            overrides=overrides,
            photos=photos,
            expected_docx=expected_docx,
            expected_xlsx=expected_xlsx,
        )


class GoldenRunner:
    """
    Run golden tests for document rendering.

    Usage:
        runner = GoldenRunner(templates_dir, output_dir)
        runner.run_scenario(scenario)
    """

    def __init__(
        self,
        templates_dir: Path,
        output_dir: Path,
        template_id: str = "base",
        measurement_config: dict[str, Any] | None = None,
    ):
        """
        Args:
            templates_dir: Path to templates directory
            output_dir: Path for rendered output files
            template_id: Template to use for rendering (or "auto" for scenario-based selection)
            measurement_config: XLSX measurement extraction config
        """
        self.templates_dir = templates_dir
        self.output_dir = output_dir
        self.template_id = template_id
        self.measurement_config = measurement_config or {
            "sheet": "Sheet1",
            "start_row": 5,
            "columns": {
                "item": "A",
                "spec": "B",
                "measured": "C",
                "unit": "D",
                "result": "E",
            },
        }

        # Normalizer for consistent comparison
        self.normalizer = Normalizer(
            exclude_fields={"generated_at", "created_at", "timestamp"},
        )

        # Extractors
        self.docx_extractor = DocxExtractor(normalizer=self.normalizer)
        self.xlsx_extractor = XlsxExtractor(
            normalizer=self.normalizer,
            measurement_config=self.measurement_config,
            extract_all_cells=True,
        )

    def _select_template_id(self, scenario: GoldenScenario) -> str:
        """
        Select template ID based on scenario.

        Uses "with_photos" template for scenarios with photos,
        otherwise uses the configured template_id.
        """
        if self.template_id != "auto":
            return self.template_id

        # Auto-select: use with_photos if scenario has photos
        if scenario.photos:
            photos_template = self.templates_dir / "with_photos"
            if photos_template.exists():
                return "with_photos"

        return "base"

    def run_scenario(
        self,
        scenario: GoldenScenario,
        assert_match: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Run a single golden scenario.

        Args:
            scenario: The scenario to run
            assert_match: Whether to assert match (raise on failure)

        Returns:
            Tuple of (docx_result, xlsx_result) extracted content
        """
        from src.render.word import DocxRenderer
        from src.render.excel import ExcelRenderer, load_manifest

        # Prepare output paths
        output_dir = self.output_dir / scenario.name
        output_dir.mkdir(parents=True, exist_ok=True)

        docx_output = output_dir / OUTPUT_DOCX_FILENAME
        xlsx_output = output_dir / OUTPUT_XLSX_FILENAME

        # Get templates (auto-select based on scenario)
        template_id = self._select_template_id(scenario)
        template_dir = self.templates_dir / template_id
        docx_template = template_dir / "report_template.docx"
        xlsx_template = template_dir / "measurements_template.xlsx"
        manifest_path = template_dir / "manifest.yaml"

        # Prepare data (input + overrides)
        data = {**scenario.input_packet}
        data.update(scenario.overrides)

        # Render DOCX
        docx_result: dict[str, Any] = {}
        if docx_template.exists():
            renderer = DocxRenderer(docx_template)
            renderer.render(
                data=data,
                output_path=docx_output,
                photos=scenario.photos if scenario.photos else None,
            )

            # Extract content
            docx_result = self.docx_extractor.extract_to_dict(docx_output)

        # Render XLSX
        xlsx_result: dict[str, Any] = {}
        if xlsx_template.exists() and manifest_path.exists():
            manifest = load_manifest(manifest_path)
            renderer = ExcelRenderer(xlsx_template, manifest)
            renderer.render(data=data, output_path=xlsx_output)

            # Extract content
            xlsx_result = self.xlsx_extractor.extract_to_dict(xlsx_output)

        # Compare if expected results exist
        if assert_match:
            if scenario.expected_docx and docx_result:
                assert_golden_match(
                    scenario.expected_docx,
                    docx_result,
                    ignore_keys={"metadata"},
                )

            if scenario.expected_xlsx and xlsx_result:
                assert_golden_match(
                    scenario.expected_xlsx,
                    xlsx_result,
                    ignore_keys={"metadata"},
                )

        return docx_result, xlsx_result

    def generate_expected(
        self,
        scenario: GoldenScenario,
    ) -> tuple[Path, Path]:
        """
        Generate expected result files for a scenario.

        WARNING: This should only be used to initialize golden files,
        not in CI. The generated files should be manually reviewed.

        Args:
            scenario: The scenario to generate expected for

        Returns:
            Tuple of (docx_json_path, xlsx_json_path)
        """
        # Run without assertion
        docx_result, xlsx_result = self.run_scenario(scenario, assert_match=False)

        # Create expected directory
        expected_dir = scenario.path / "expected"
        expected_dir.mkdir(parents=True, exist_ok=True)

        # Save DOCX expected
        docx_json_path = expected_dir / "docx.json"
        with open(docx_json_path, "w", encoding="utf-8") as f:
            json.dump(docx_result, f, ensure_ascii=False, indent=2)

        # Save XLSX expected
        xlsx_json_path = expected_dir / "xlsx.json"
        with open(xlsx_json_path, "w", encoding="utf-8") as f:
            json.dump(xlsx_result, f, ensure_ascii=False, indent=2)

        return docx_json_path, xlsx_json_path


def discover_scenarios(golden_dir: Path) -> list[GoldenScenario]:
    """
    Discover all golden scenarios in a directory.

    Args:
        golden_dir: Path to golden tests directory

    Returns:
        List of GoldenScenario objects
    """
    scenarios = []

    for scenario_path in golden_dir.iterdir():
        if scenario_path.is_dir() and (scenario_path / "input_packet.json").exists():
            try:
                scenario = GoldenScenario.load(scenario_path)
                scenarios.append(scenario)
            except Exception as e:
                print(f"Warning: Failed to load scenario {scenario_path}: {e}")

    return sorted(scenarios, key=lambda s: s.name)
