from src.combos import CardOption, cheapest_cover

JPY_ILS = 1 / 51.357


def jp_cards():
    return [
        CardOption(5000, round(5000 * JPY_ILS * 1.108, 2), "Eneba", "e"),
        CardOption(1100, round(1100 * JPY_ILS * 1.16, 2), "SEAGM", "s"),
        CardOption(3000, round(3000 * JPY_ILS * 1.159, 2), "SEAGM", "s"),
        CardOption(1000, round(1000 * JPY_ILS * 1.537, 2), "Eneba", "e"),
    ]


def test_ps_plus_extra_japan():
    c = cheapest_cover(11700, jp_cards())
    assert {(o.face, n) for o, n in c.picks} == {(5000, 2), (1100, 2)}
    assert c.total_face == 12200 and c.leftover(11700) == 500


def test_ps_plus_essential_japan():
    c = cheapest_cover(6800, jp_cards())
    assert {(o.face, n) for o, n in c.picks} == {(5000, 1), (1100, 2)}


def test_usd_price_with_cents():
    cards = [CardOption(100, 294.0, "Matiex", "m"), CardOption(50, 147.0, "Matiex", "m"),
             CardOption(25, 75.8, "Matiex", "m"), CardOption(5, 16.9, "Matiex", "m")]
    c = cheapest_cover(79.99, cards)
    assert c.total_face >= 79.99 and c.total_face == 80


def test_no_cards():
    assert cheapest_cover(1000, []) is None
