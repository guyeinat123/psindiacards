from pathlib import Path

from src import games, pricing

FIX = Path(__file__).parent / "fixtures"
RATES = {"INR": 31.313, "USD": 0.32508, "JPY": 51.357}


def pages():
    return {r: games.parse_concept((FIX / f"ps_{r.lower()}.html").read_text()) for r in ("IN", "US", "JP")}


def test_parse_concept_reads_every_edition_including_preorder():
    _, us = pages()["US"]
    assert us["CODMW4STANDARD01"].price == 69.99 and us["CODMW4STANDARD01"].currency == "USD"
    assert us["CODMW4VAULT00001"].price == 99.99
    assert "CODWZ2BUNDLE0001" not in us          # free-to-play Warzone is skipped
    _, india = pages()["IN"]
    assert india["CODMW4STANDARD01"].price == 5999 and india["CODMW4STANDARD01"].name == "MW4 Standard"
    _, jp = pages()["JP"]
    assert jp["CODMW4STANDARD01"].price == 9800


def test_compare_prefers_standard_edition_and_applies_card_cost():
    wallet = {"IN": 1.081 / RATES["INR"], "US": 0.956 / RATES["USD"], "JP": 1.159 / RATES["JPY"]}
    c = games.compare("10001130", pages(), wallet)
    assert c.edition_name == "MW4 Standard"
    assert [r.region for r in c.rows] == ["US", "IN", "JP"]
    assert c.best.effective_ils == round(69.99 * 0.956 / RATES["USD"], 2)
    assert c.best.url == "https://store.playstation.com/en-us/concept/10001130"


def test_compare_skips_regions_without_card_or_listing():
    c = games.compare("1", {"IN": ("t", {}), "US": pages()["US"]}, {"US": 3.0, "JP": 0.06})
    assert [r.region for r in c.rows] == ["US"]


def test_concept_id_from_lines():
    assert games.concept_id_from("https://store.playstation.com/en-in/concept/10001130/") == "10001130"
    assert games.concept_id_from("10001130") == "10001130"
    page = '..."conceptId","value":"10001130"}]...'
    assert games.concept_id_from("https://store.playstation.com/en-us/product/UP0002-X", page) == "10001130"


def test_read_watchlist_ignores_comments(tmp_path):
    f = tmp_path / "games.txt"
    f.write_text("# header\n\nhttps://store.playstation.com/en-us/concept/1  # note\n")
    assert games.read_watchlist(str(f)) == ["https://store.playstation.com/en-us/concept/1"]


def test_game_decision():
    assert pricing.game_decision(200, None, 10) == (False, 200)        # first sighting
    assert pricing.game_decision(195, 200, 10) == (False, 200)         # small dip
    assert pricing.game_decision(170, 200, 10) == (True, 170)          # sale -> alert
    assert pricing.game_decision(170, 170, 10) == (False, 170)         # same sale, no repeat
    assert pricing.game_decision(210, 170, 10) == (False, 210)         # sale over -> re-arm
