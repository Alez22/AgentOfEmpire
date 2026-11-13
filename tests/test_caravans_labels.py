"""Roads of the world, phase 2, step 3: the chronicle's sentences for the
caravans (server/ui/labels.py)."""

from server.ui import labels


def test_the_chronicle_tells_caravans_arrived_and_robbed():
    out = labels.event_label("caravan_arrived", {"leg": "out", "goods": {"food": 100}, "week": 2})
    assert out == "La carovana è arrivata alla fiera con 100 cibo."
    back = labels.event_label("caravan_arrived", {"leg": "back", "goods": {"wood": 50, "stone": 50}, "week": 3})
    assert back == "La carovana è tornata dalla fiera con 50 legno e 50 pietra."
    robbed = {"leg": "back", "goods": {"food": 100}, "band": 2, "adults": 6, "week": 3, "x": 30, "y": 30}
    assert labels.event_label("caravan_robbed", robbed) == (
        "Una banda di una decina di briganti ha rapinato la carovana di ritorno dalla fiera: persi 100 cibo.")
    assert labels.event_alert("caravan_robbed", robbed) == ("raid", "Carovana rapinata")


def test_trades_on_the_road_say_when_they_arrive():
    bought = labels.event_label("trade_bought", {"good": "food", "lots": 2, "gold": 22, "road": True})
    assert bought.endswith("In viaggio verso casa: arrivano a fine mese.")
    sold = labels.event_label("trade_on_sale", {"good": "wood", "lots": 1, "road": True})
    assert sold.endswith("in vendita dal mese prossimo.")
    assert labels.event_label("trade_on_sale", {"good": "wood", "lots": 1}) == "Messi in vendita al mercato 1 lotto di legno."


def test_a_band_met_on_the_road_is_seen_there():
    seen = {"band": 2, "adults": 3, "week": 3, "x": 30, "y": 29, "tower": False, "road": True}
    assert labels.event_label("band_seen", seen) == "Avvistata una piccola banda sulla strada della fiera."
