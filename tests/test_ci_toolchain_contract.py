from pathlib import Path


def test_ci_pins_uv_instead_of_querying_latest_release():
    workflow = Path(".github/workflows/context-graph.yml").read_text()
    assert "astral-sh/setup-uv@v6" in workflow
    assert 'version: "0.11.21"' in workflow
