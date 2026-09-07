from __future__ import annotations

import importlib.util
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_anonymous_example_is_valid_for_harvest_and_luna() -> None:
    harvest = load_module("relocated_harvest", HERE / "harvest.py")
    luna = load_module("relocated_luna", HERE / "annotate.py")
    profile_path = REPO_ROOT / "profile.example.yaml"

    profile = harvest.load_profile_contract(profile_path)
    safe_projection = luna._load_safe_profile_contract(profile_path)

    assert profile["contract_version"] == 1
    assert "typescript" in profile["fit_terms"]
    assert safe_projection["candidate"]["location"] == "Example City"


def test_container_does_not_copy_a_profile() -> None:
    dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY scraper/ /app/scraper/" in dockerfile
    assert "profile.example.yaml" not in dockerfile
    assert "profile.yaml" not in dockerfile
    assert 'ENTRYPOINT ["python", "/app/scraper/harvest.py"' in dockerfile


def test_public_tree_has_no_host_integrations() -> None:
    checked = [
        path
        for path in HERE.rglob("*")
        if path.is_file()
        and path != Path(__file__)
        and "__pycache__" not in path.parts
    ]
    checked.append(REPO_ROOT / "profile.example.yaml")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked)

    notification_name = "".join(("Tele", "gram"))
    for forbidden in (notification_name, notification_name.casefold(), "sync-tailnet"):
        assert forbidden not in combined
    home_names = set(
        re.findall(r"/(?:Users|home)/([^/\s\"']+)", combined)
    )
    assert home_names <= {"private", "example"}
