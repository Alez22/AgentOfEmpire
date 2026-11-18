"""The realm's first page, pure parts (server/ui/realm_view.py)."""

from types import SimpleNamespace

from server.ui.realm_view import hud_chips, month_action


def _view(food=100, wood=50, stone=20, gold=30, adults=40):
    return SimpleNamespace(food=food, wood=wood, stone=stone, gold=gold, children=10, adults=adults, elders=5)


def test_the_hud_shows_the_change_since_last_month():
    chips = {c["key"]: c for c in hud_chips(_view(food=120, adults=41), _view())}
    assert chips["food"]["value"] == 120 and chips["food"]["delta"] == 20
    assert chips["people"]["value"] == 56 and chips["people"]["delta"] == 1
    assert chips["gold"]["delta"] == 0


def test_the_first_month_has_no_change():
    assert all(c["delta"] is None for c in hud_chips(_view(), None))


def _action(**changes):
    args = dict(realm_id=7, turn=3, open_turn=3, game_over=None, automatic=False, running=False,
                rounds_held=0, plan_ready=False, approved=False)
    args.update(changes)
    return month_action(**args)


def test_the_sheet_follows_the_council():
    assert _action()["kind"] == "post" and _action()["href"] == "/ui/realms/7/meeting"
    assert _action(running=True)["href"] == "/ui/realms/7/council"
    ready = _action(rounds_held=1, plan_ready=True)
    assert ready["label"] == "Leggi il piano" and ready["kind"] == "link"
    approved = _action(rounds_held=1, plan_ready=True, approved=True)
    assert approved["href"] == "/ui/realms/7/resolve" and approved["label"] == "Chiudi marzo"
    assert _action(rounds_held=1)["label"] == "Vai al consiglio"


def test_a_fallen_realm_has_no_action():
    fallen = _action(game_over="revolt")
    assert fallen["kind"] is None and "ribellato" in fallen["line"]
