from pathlib import Path

import pytest

from src import psplus
from src.sources.base import Blocked

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("region,essential12,extra12,currency", [
    ("IN", 5139, 8709, "INR"), ("US", 79.99, 134.99, "USD"), ("JP", 6800, 11700, "JPY"),
])
def test_parse_all_tiers(region, essential12, extra12, currency):
    plans = psplus.parse((FIX / f"psplus_{region.lower()}.html").read_text(), region)
    assert len(plans) == 9                                   # 3 tiers x 1/3/12 months
    assert plans[("Essential", 12)].price == essential12
    assert plans[("Extra", 12)].price == extra12
    assert all(p.currency == currency and not p.on_sale for p in plans.values())


def test_parse_rejects_empty_page():
    with pytest.raises(Blocked):
        psplus.parse("<html></html>", "US")
