"""Container dependency and build-context drift checks."""

from pathlib import Path
from tomllib import loads

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def _normalized(requirement: str) -> str:
    return requirement.casefold().replace("[asyncio]", "")


def test_runtime_requirements_match_project_dependencies() -> None:
    pyproject = loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_dependencies = {_normalized(value) for value in pyproject["project"]["dependencies"]}
    embedding_dependencies = {
        _normalized(value) for value in pyproject["project"]["optional-dependencies"]["embeddings"]
    }
    runtime_dependencies = {
        _normalized(line)
        for line in (BACKEND_ROOT / "requirements.runtime.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#") and not line.startswith("setuptools==")
    }

    assert runtime_dependencies == project_dependencies | embedding_dependencies


def test_cpu_runtime_pins_cpu_only_torch_before_embedding_dependencies() -> None:
    cpu_requirements = (BACKEND_ROOT / "requirements.cpu.txt").read_text(encoding="utf-8")
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "--index-url https://download.pytorch.org/whl/cpu" in cpu_requirements
    assert "torch==2.9.1+cpu" in cpu_requirements
    assert dockerfile.index("requirements.cpu.txt") < dockerfile.index("requirements.runtime.txt")


def test_docker_context_excludes_tests_and_local_runtime_data() -> None:
    dockerignore = (BACKEND_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "tests" in dockerignore
    assert "data" in dockerignore
    assert "reports" in dockerignore
    assert "artifacts" in dockerignore


def test_runtime_image_packages_alembic_configuration_and_migrations() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    alembic_configuration = (BACKEND_ROOT / "alembic.ini").read_text(encoding="utf-8")
    hostinger_compose = (PROJECT_ROOT / "compose.hostinger.yaml").read_text(encoding="utf-8")

    assert "COPY alembic.ini ./" in dockerfile
    assert "COPY migrations ./migrations" in dockerfile
    assert "test -f /app/alembic.ini" in dockerfile
    assert "test -f /app/migrations/env.py" in dockerfile
    assert "test -d /app/migrations/versions" in dockerfile
    assert "script_location = %(here)s/migrations" in alembic_configuration
    assert "working_dir: /app" in hostinger_compose
    assert "image: hotel-support-bot-hostinger-backend:latest" in hostinger_compose
    assert "      - --config\n      - /app/alembic.ini" in hostinger_compose
    assert "./backend/alembic.ini:/app/alembic.ini" not in hostinger_compose
    assert "./backend/migrations:/app/migrations" not in hostinger_compose
