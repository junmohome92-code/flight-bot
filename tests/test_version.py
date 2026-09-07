from pathlib import Path


def test_version_marker_matches_package_release():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text(encoding="utf-8").strip() == "0.5.0"
    assert 'version = "0.5.0"' in (root / "pyproject.toml").read_text(encoding="utf-8")
