"""Prüft die mitgelieferte config/config.yaml (nicht die Test-Konfiguration)."""
import pytest

from app.config import ROOT, validate
from app.fetcher import rule_topics


@pytest.fixture(scope="module")
def real_cfg():
    import yaml
    return validate(yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8")))


def test_real_config_is_valid(real_cfg):
    ids = [t["id"] for t in real_cfg["topics"]]
    assert "bestpreise" in ids and "regional" in ids
    assert any(s["topic"] == "bestpreise" for s in real_cfg["sources"])


@pytest.mark.parametrize("title", [
    "Samsung 990 Pro 2 TB zum Bestpreis",
    "AirPods Pro 2 auf Tiefstpreis gefallen",
    "Prime Day: Die besten Angebote für Gamer",
    "Schnäppchen: Nintendo Switch OLED günstig wie nie",
    "Kaffeevollautomat 40 % reduziert",
])
def test_deal_titles_get_bestpreise(real_cfg, title):
    assert "bestpreise" in rule_topics(real_cfg, title, "")


@pytest.mark.parametrize("title", [
    "Preissturz beim Öl: Opec reagiert",
    "Deal mit dem Iran: USA verhandeln weiter",
    "Bahn hat neue Sprinter-Verbindungen im Angebot",
    "Inflation sinkt auf 1,9 Prozent",
    "Regierung plant Rabatt bei Netzentgelten",
])
def test_news_titles_are_not_deals(real_cfg, title):
    assert "bestpreise" not in rule_topics(real_cfg, title, "")
