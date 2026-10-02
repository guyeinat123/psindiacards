import json
from pathlib import Path

import pytest

from src.sources import amazon_in, dlcompare, eneba, seagm, simplygaming
from src.sources.base import Blocked

FIX = Path(__file__).parent / "fixtures"


def test_dlcompare_india_only_with_card_fee():
    offers = dlcompare.parse((FIX / "dlcompare.html").read_text())
    assert offers and all(o.currency == "INR" for o in offers)
    assert "Kinguin" not in {o.store for o in offers if o.face_inr == 1000}   # its ₹1000 is "Asia"
    eneba_1000 = next(o for o in offers if o.store == "Eneba" and o.face_inr == 1000)
    assert eneba_1000.price == 1576.63            # credit-card fee price, not the bare 1419.75
    assert eneba_1000.note == "coupon 3DLC"
    assert {o.face_inr for o in offers} <= {1000, 2000, 3000, 4000, 5000, 8000}


def test_dlcompare_block_page_raises():
    with pytest.raises(Blocked):
        dlcompare.parse("<html>Just a moment...</html>")


def test_seagm_applies_discount():
    offers = seagm.parse((FIX / "seagm.html").read_text(), fee_pct=3)
    by_face = {o.face_inr: o for o in offers}
    assert by_face[1000].price == 57.35 and by_face[1000].currency == "MYR"
    assert by_face[1000].extra_fee_pct == 3
    assert set(by_face) == {1000, 2000, 3000, 4000, 5000, 7000, 8000}


def test_simplygaming_face_value_and_stock():
    offers = simplygaming.parse(json.loads((FIX / "simplygaming.json").read_text()))
    by_face = {o.face_inr: o for o in offers}
    assert by_face[1000].price == 1000.0 and by_face[9000].price == 9000.0
    assert not any(o.in_stock for o in offers)     # all sold out when the fixture was saved


def test_eneba_reads_cheapest_auction():
    offers = eneba.parse((FIX / "eneba.html").read_text(), fee_pct=11)
    assert offers
    for o in offers:
        assert o.store == "Eneba" and o.currency and o.price > 0 and o.extra_fee_pct == 11
        assert o.url.startswith("https://www.eneba.com/psn-playstation-network-card-rs-")


def test_amazon_keepa_parse():
    data = {"products": [
        {"asin": "A1", "stats": {"current": [100000, 99500]}},   # ₹1000 by Amazon, ₹995 3rd party
        {"asin": "A2", "stats": {"current": [-1, -1]}},          # out of stock
    ]}
    offers = amazon_in.parse(data, {"A1": 1000, "A2": 2000})
    assert offers[0].price == 995.0 and offers[0].in_stock
    assert not offers[1].in_stock


def test_matiex_store_api():
    from src.sources import matiex
    offers = matiex.parse(json.loads((FIX / "matiex.json").read_text()))
    by_face = {o.face_inr: o for o in offers}
    assert by_face[1000].price == 11.5 and by_face[1000].currency == "USD"
    assert set(by_face) == {1000, 2000, 3000, 4000, 5000}


def test_egiftcards_nz_variations():
    from src.sources import egiftcards_nz
    offers = egiftcards_nz.parse((FIX / "egiftcards_nz.html").read_text())
    by_face = {o.face_inr: o for o in offers}
    assert by_face[1000].price == 19.5 and by_face[1000].currency == "NZD"
    assert by_face[5000].in_stock
    with pytest.raises(Blocked):
        egiftcards_nz.parse("<html>nothing</html>")
