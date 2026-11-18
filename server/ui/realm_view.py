"""@brief The realm's first page: the map with a HUD on top and a bottom sheet
(docs/DESIGN.md, "The map as the realm's first page").

Pure functions over what the route loads; the template only writes out what
they return. The HUD shows what the sovereign may count (sovereign_state:
never the mood); the sheet's action follows the council's state, while the
approval itself stays on the council page.
"""

from server.ui import labels

# (key, Italian name) of the HUD's stocks, in the order they are shown.
HUD_STOCKS = (("food", "Cibo"), ("wood", "Legna"), ("stone", "Pietra"), ("gold", "Oro"), ("people", "Abitanti"))


def _stocks(state) -> dict[str, int]:
    return {"food": state.food, "wood": state.wood, "stone": state.stone, "gold": state.gold,
            "people": state.children + state.adults + state.elders}


def hud_chips(state, before) -> list[dict]:
    """@brief The HUD's stocks with their change since the previous snapshot.
    @param state The sovereign's view of the realm now.
    @param before The view a month earlier, or None in the first month (no change shown).
    @return [{"key", "name", "value", "delta" (int or None)}]
    """
    now = _stocks(state)
    was = _stocks(before) if before is not None else None
    return [{"key": key, "name": name, "value": now[key], "delta": None if was is None else now[key] - was[key]}
            for key, name in HUD_STOCKS]


def voice_scroll(text: str | None) -> dict | None:
    """@brief The Voice of the square, read on a tap on the square (its card)
    and in the sheet; nothing lies on the map. None when the square has not spoken."""
    if not text:
        return None
    return {"full": text.strip()}


def month_action(realm_id: int, turn: int, open_turn: int | None, game_over: str | None, automatic: bool,
                 running: bool, rounds_held: int, plan_ready: bool, approved: bool) -> dict:
    """@brief The one line on the month and the one action of the closed sheet.
    @return {"title", "line", "kind", "label", "href"}; kind is "post" (a form to
            href), "link", or None (no action).
    """
    month = labels.month_name(turn)
    council = f"/ui/realms/{realm_id}/council"
    action = {"title": f"{month.capitalize()} è aperto", "line": "", "kind": None, "label": "", "href": ""}
    if game_over:
        return {**action, "title": "Il regno è caduto", "line": labels.GAME_OVER.get(game_over, game_over)}
    if open_turn is None:
        return {**action, "title": month.capitalize(), "line": "Nessun mese aperto in questa partita."}
    if automatic:
        return {**action, "line": "Mese automatico: il consiglio governa secondo i tuoi mandati.",
                "kind": "link", "label": "Segui il consiglio", "href": council}
    if running:
        return {**action, "line": "Il consiglio è riunito.", "kind": "link", "label": "Segui il consiglio",
                "href": council}
    if rounds_held == 0:
        return {**action, "line": "Il consiglio non si è ancora riunito.", "kind": "post", "label": "Convoca",
                "href": f"/ui/realms/{realm_id}/meeting"}
    if approved:
        return {**action, "line": "Il piano è approvato.", "kind": "post", "label": f"Chiudi {month}",
                "href": f"/ui/realms/{realm_id}/resolve"}
    if plan_ready:
        return {**action, "line": "Il piano del consiglio aspetta la tua approvazione.", "kind": "link",
                "label": "Leggi il piano", "href": council}
    return {**action, "line": "Il consiglio si è riunito senza un piano.", "kind": "link",
            "label": "Vai al consiglio", "href": council}
