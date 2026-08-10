import json
from pathlib import Path

CATALOG = Path(__file__).parents[1] / "pretalx_speakerops" / "data" / "conferences"


def _series(filename):
    return json.loads((CATALOG / filename).read_text(encoding="utf-8"))["series"][0]


def _edition(series, external_key):
    return next(
        edition for edition in series["editions"] if edition["external_key"] == external_key
    )


def test_jsconf_belgium_2018_uses_the_archived_official_schedule():
    series = _series("jsconf_belgium_full.json")
    edition = _edition(series, "belgium-2018")

    assert edition["source_url"] == (
        "https://web.archive.org/web/20190819194010id_/https://www.jsconf.be/en/schedule"
    )
    assert edition["source_version"].startswith("wayback:20190819194010:")
    assert len(edition["talks"]) == 24
    assert sum(len(talk["speakers"]) for talk in edition["talks"]) == 27
    assert all(talk["title"] and talk["speakers"] for talk in edition["talks"])
    assert not any(
        gap.get("scope") == "JSConf Belgium 2018" for gap in series["source_policy"]["known_gaps"]
    )


def test_recovered_pycon_de_editions_are_credited_and_provenanced():
    series = _series("pycon.json")
    expected = {
        "de-2011": (54, 55),
        "de-2012": (69, 71),
        "de-2013": (70, 79),
        "de-pydata-2018": (79, 85),
    }

    for external_key, (talks, credits) in expected.items():
        edition = _edition(series, external_key)
        assert len(edition["talks"]) == talks
        assert sum(len(talk["speakers"]) for talk in edition["talks"]) == credits
        assert all(talk["title"] and talk["speakers"] for talk in edition["talks"])
        assert all(talk["source_url"].startswith("https://") for talk in edition["talks"])
        assert edition["source_version"]

    assert _edition(series, "de-pydata-2018")["source_url"] == ("https://2018.pycon.de/schedule/")


def test_pycon_de_lineage_does_not_invent_2014_or_2015_editions():
    series = _series("pycon.json")
    edition_keys = {edition["external_key"] for edition in series["editions"]}
    gaps = {gap["item"]: gap for gap in series["source_policy"]["known_gaps"]}

    assert "de-2014" not in edition_keys
    assert "de-2015" not in edition_keys
    assert "PyCon DE/PyData before 2016" not in gaps
    assert "PyCon DE & PyData 2018" not in gaps
    assert gaps["PyCon DE 2014-2015"]["scope"] == "lineage"
    assert "satellite within EuroPython 2014" in gaps["PyCon DE 2014-2015"]["reason"]
