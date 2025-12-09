"""
Pytest fixtures for the pipeline tests.

AGENTS.md 규칙에 따른 테스트 구성:
- 정상 케이스, 필수 필드 누락 케이스 등 분리
"""

import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import uvicorn
import yaml

# =============================================================================
# Path Fixtures
# =============================================================================

@pytest.fixture
def project_root() -> Path:
    """프로젝트 루트 경로."""
    return Path(__file__).parent.parent


@pytest.fixture
def definition_path(project_root: Path) -> Path:
    """definition.yaml 경로."""
    return project_root / "definition.yaml"


@pytest.fixture
def default_config_path(project_root: Path) -> Path:
    """default.yaml 경로."""
    return project_root / "default.yaml"


@pytest.fixture
def default_config(default_config_path: Path) -> dict:
    """기본 설정 로드."""
    with open(default_config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# =============================================================================
# Job Fixtures
# =============================================================================

@pytest.fixture
def sample_pass_job(tmp_path: Path) -> Generator[Path, None, None]:
    """
    정상 케이스 job 폴더.

    포함:
    - packet.xlsx (모의)
    - photos/raw/ (01_overview.jpg, 02_label_serial.jpg)
    """
    job_dir = tmp_path / "sample_pass"
    job_dir.mkdir()

    # 입력 폴더 구조
    (job_dir / "inputs" / "uploads").mkdir(parents=True)
    (job_dir / "photos" / "raw").mkdir(parents=True)
    (job_dir / "photos" / "derived" / "_trash").mkdir(parents=True)
    (job_dir / "logs").mkdir()
    (job_dir / "deliverables").mkdir()

    # 모의 사진 파일 생성
    (job_dir / "photos" / "raw" / "01_overview.jpg").write_bytes(b"fake jpg")
    (job_dir / "photos" / "raw" / "02_label_serial.jpg").write_bytes(b"fake jpg")

    yield job_dir

    # Cleanup (optional, tmp_path handles it)


@pytest.fixture
def sample_fail_job(tmp_path: Path) -> Generator[Path, None, None]:
    """
    필수 필드 누락 케이스.

    포함:
    - photos/raw/ (필수 사진 누락)
    """
    job_dir = tmp_path / "sample_fail"
    job_dir.mkdir()

    # 최소 구조만
    (job_dir / "photos" / "raw").mkdir(parents=True)

    yield job_dir


@pytest.fixture
def sample_packet() -> dict:
    """정상 케이스 packet 데이터."""
    return {
        "wo_no": "WO-001",
        "line": "L1",
        "part_no": "PART-A",
        "lot": "LOT-001",
        "result": "PASS",
        "inspector": "홍길동",
        "date": "2024-01-15",
        "remark": "테스트 비고",
        "measurements": [
            {
                "item": "길이",
                "spec": "10±0.1",
                "measured": "10.05",
                "unit": "mm",
                "result": "PASS",
            },
            {
                "item": "폭",
                "spec": "5±0.1",
                "measured": "5.02",
                "unit": "mm",
                "result": "PASS",
            },
        ],
    }


@pytest.fixture
def sample_packet_missing_critical() -> dict:
    """critical 필드 누락 packet."""
    return {
        # wo_no 누락
        "line": "L1",
        "part_no": "PART-A",
        "lot": "LOT-001",
        "result": "PASS",
    }


# =============================================================================
# Config Fixtures
# =============================================================================

@pytest.fixture
def test_config() -> dict:
    """테스트용 설정."""
    return {
        "paths": {
            "lock_dir": ".lock",
        },
        "pipeline": {
            "lock_retry_interval": 0.1,
            "lock_max_retries": 3,
        },
        "hashing": {
            "exclude_from_packet_hash": ["free_text"],
        },
    }


# =============================================================================
# Browser Test Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def live_server() -> Generator[str, None, None]:
    """
    FastAPI 앱을 백그라운드에서 실행하는 fixture.

    Returns:
        서버 URL (예: "http://localhost:8765")
    """
    from src.app.main import app

    # 테스트용 포트
    port = 8765
    host = "127.0.0.1"

    # 별도 스레드에서 서버 실행
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    def run_server() -> None:
        import asyncio
        asyncio.run(server.serve())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # 서버가 준비될 때까지 대기
    base_url = f"http://{host}:{port}"
    max_attempts = 30
    for _ in range(max_attempts):
        try:
            import httpx
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("Failed to start test server")

    yield base_url

    # 서버 종료
    server.should_exit = True
