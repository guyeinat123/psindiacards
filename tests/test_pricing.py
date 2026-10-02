from src import pricing
from src.models import Offer

RATES = {"ILS": 1.0, "INR": 31.313, "MYR": 1.3278, "USD": 0.32508, "EUR": 0.28773}


def offer(price, currency="INR", face=1000, fee=0.0, in_stock=True, store="S"):
    return Offer("t", store, face, price, currency, "u", in_stock=in_stock, extra_fee_pct=fee)


def test_face_value_card_markup_is_only_the_bank_fee():
    [o] = pricing.apply([offer(1000)], RATES, foreign_fee_pct=2.5)
    assert o.markup_pct == 2.5
    assert o.effective_ils == round(1000 / 31.313 * 1.025, 2)


def test_foreign_currency_and_store_fee_are_applied():
    [o] = pricing.apply([offer(57.35, "MYR", fee=3)], RATES, foreign_fee_pct=0)
    assert o.effective_ils == round(57.35 / 1.3278 * 1.03, 2)


def test_unknown_currency_dropped():
    assert pricing.apply([offer(10, "GBP")], RATES, 0) == []


def test_broken_listing_dropped():
    assert pricing.apply([offer(501160.64, face=8000)], RATES, 0) == []


def test_best_by_denomination_sorts_and_skips_out_of_stock():
    offers = pricing.apply([
        offer(1100, store="B"), offer(1050, store="A"), offer(900, store="OOS", in_stock=False),
        offer(2100, face=2000),
    ], RATES, 0)
    best = pricing.best_by_denomination(offers, [1000, 2000, 5000])
    assert [o.store for o in best[1000]] == ["A", "B"]
    assert 5000 not in best


def test_should_alert_rules():
    [good] = pricing.apply([offer(1020)], RATES, 0)       # +2%
    [bad] = pricing.apply([offer(1500)], RATES, 0)        # +50%
    assert pricing.should_alert(good, None, 15, 1)
    assert not pricing.should_alert(bad, None, 15, 1)
    assert not pricing.should_alert(good, good.effective_ils, 15, 1)          # same deal again
    assert not pricing.should_alert(good, good.effective_ils * 1.005, 15, 1)  # <1% cheaper
    assert pricing.should_alert(good, good.effective_ils * 1.02, 15, 1)       # 2% cheaper
