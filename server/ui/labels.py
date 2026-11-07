"""@brief Italian wording of engine data for the web UI (player-facing text).

Code identifiers stay English; only what the player reads is translated
here, in one place. An unknown key falls back to the raw identifier, so a
new engine value shows up (ugly but visible) instead of crashing the page.
"""

BUILDINGS = {"farm": "fattoria", "sawmill": "segheria", "quarry": "cava", "house": "casa"}
RATIONS = {"reduced": "ridotta", "normal": "normale", "abundant": "abbondante"}
UNREST = {"calm": "calma", "protests": "proteste", "strike": "sciopero", "revolt": "rivolta"}
SEASONS = {"winter": "inverno", "spring": "primavera", "summer": "estate", "autumn": "autunno"}
MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
          "agosto", "settembre", "ottobre", "novembre", "dicembre")
GAME_OVER = {"revolt": "Il popolo si è ribellato: il regno è perduto.",
             "extinction": "Non è rimasto nessuno: il regno è scomparso."}

REJECTIONS = {
    "UNKNOWN_ACTION": "ordine sconosciuto",
    "INVALID_PARAM": "valori non validi",
    "INSUFFICIENT_RESOURCES": "risorse insufficienti",
    "NOT_ENOUGH_WORKERS": "non ci sono abbastanza adulti",
    "NO_FREE_TILE": "nessuna casella libera",
    "DUPLICATE_POLICY": "già deciso in questo turno",
    # Reasons the council module gives for discarded proposals.
    "NOT_ROLE_ACTION": "fuori dalle sue competenze",
    "TOO_MANY_PROPOSALS": "troppe proposte",
    "UNKNOWN_PROPOSER": "senza un ministro responsabile",
}

# Council members: display name, colour and initial (from the UX mockups).
ROLES = {
    "treasurer": {"name": "Il Tesoriere", "color": "#8FC07A", "initial": "T"},
    "architect": {"name": "L'Architetta", "color": "#7DB3E0", "initial": "A"},
    "chancellor": {"name": "Il Cancelliere", "color": "#D4AF5A", "initial": "C"},
    "square_voice": {"name": "La piazza", "color": "#C9A27E", "initial": "P"},
    "people": {"name": "Il popolo", "color": "#B7A88A", "initial": "V"},
}
SOVEREIGN = {"name": "Il sovrano", "color": "#ECE5D6", "initial": "S"}


def month_name(turn: int) -> str:
    return MONTHS[(turn - 1) % 12]


def order_label(order: dict) -> str:
    """@brief 'Costruire una fattoria', 'Tasse al 12%', ..."""
    action = order.get("action")
    if action == "build":
        return f"Costruire: {BUILDINGS.get(order.get('building'), order.get('building'))}"
    if action == "set_tax":
        return f"Tasse al {order.get('rate')}%"
    if action == "set_ration":
        return f"Razione {RATIONS.get(order.get('ration'), order.get('ration'))}"
    if action == "hold_feast":
        return f"Festa per il popolo: {order.get('gold')} oro"
    if action == "assign_workers":
        return (f"Lavoratori: {order.get('food')} nei campi, {order.get('wood')} nei boschi, "
                f"{order.get('stone')} nelle cave")
    return str(order)


def rejection_label(code: str | None) -> str:
    return REJECTIONS.get(code or "", code or "")


def event_label(kind: str, data: dict) -> str:
    """@brief One sentence per engine event."""
    if kind == "famine":
        return f"Carestia: è mancato il {data.get('missing_pct')}% del cibo necessario."
    if kind == "unrest_changed":
        return (f"Il popolo passa da {UNREST.get(data.get('from'), data.get('from'))} "
                f"a {UNREST.get(data.get('to'), data.get('to'))}.")
    if kind == "game_over":
        return GAME_OVER.get(data.get("reason"), f"Fine della partita: {data.get('reason')}.")
    if kind == "building_completed":
        return f"Completata una {BUILDINGS.get(data.get('kind'), data.get('kind'))}."
    if kind == "season_end":
        return f"Finisce la stagione: {SEASONS.get(data.get('season'), data.get('season'))}."
    if kind == "demography":
        return f"Nati {data.get('births')}, morti {data.get('deaths')}."
    if kind == "food_spoiled":
        return f"Andato a male nei granai: {data.get('amount')} cibo."
    if kind == "upkeep_unpaid":
        return "Manutenzione non pagata: gli edifici hanno reso la metà."
    if kind == "rule_workers_to_food":
        return f"Scorte basse: {data.get('moved')} adulti mandati nei campi."
    if kind == "audience":
        name = ROLES.get(data.get("role"), {}).get("name", data.get("role"))
        return f"Hai ricevuto in privato {name}."
    if kind == "workers_rescaled":
        return "Meno adulti di prima: i lavoratori sono stati ridistribuiti."
    if kind == "salaries_unpaid":
        return f"L'oro non bastava: i consiglieri non hanno ricevuto il salario ({data.get('salaries')} oro)."
    return f"{kind}: {data}"


def people_words(effort_pct: int, birth_pct: int) -> str:
    """@brief What the people do this month, as the sovereign sees it."""
    if effort_pct >= 5:
        work = "I contadini lavorano con slancio"
    elif effort_pct > 0:
        work = "I contadini lavorano volentieri"
    elif effort_pct == 0:
        work = "I contadini lavorano come sempre"
    elif effort_pct > -10:
        work = "I contadini lavorano svogliati"
    else:
        work = "I contadini lavorano a stento"
    if birth_pct > 100:
        families = "le famiglie vogliono figli"
    elif birth_pct < 100:
        families = "le famiglie rimandano i figli"
    else:
        families = "le famiglie vivono come sempre"
    return f"{work}; {families}."


PETITION_ANSWERS = {"granted": "esaudita", "refused": "respinta"}
