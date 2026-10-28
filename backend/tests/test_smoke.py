from compliance.config import REPO_ROOT, get_settings


def test_settings_load():
    s = get_settings()
    assert s.nebius_base_url.startswith("https://")
    assert (REPO_ROOT / "justfile").exists()


def test_core_deps_import():
    import ifcopenshell  # noqa: F401
    import shapely  # noqa: F401
    import yaml  # noqa: F401
