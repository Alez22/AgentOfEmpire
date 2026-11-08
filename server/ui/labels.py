"""@brief Italian wording of engine data for the web UI (player-facing text).

Code identifiers stay English; only what the player reads is translated
here, in one place. An unknown key falls back to the raw identifier, so a
new engine value shows up (ugly but visible) instead of crashing the page.
"""

BUILDINGS = {"farm": "fattoria", "sawmill": "segheria", "quarry": "cava", "house": "casa", "market": "mercato"}
MASCULINE_BUILDINGS = ("market",)  # "Completato un mercato", the others "Completata una ..."
CLASSES_IT = {"merchants": "I mercanti"}
GOODS_IT = {"food": "cibo", "wood": "legno", "stone": "pietra"}


def lots_of(lots, good: str) -> str:
    """@brief "1 lotto di legno", "3 lotti di pietra"."""
    return f"{lots} {'lotto' if lots == 1 else 'lotti'} di {GOODS_IT.get(good, good)}"
TERRAINS = {"plain": "pianura", "forest": "bosco", "hill": "collina"}
DIRECTIONS = {"north": "nord", "south": "sud", "east": "est", "west": "ovest"}
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
    # The market (engine/market.py).
    "NO_MARKET": "in questo mondo non c'è mercato",
    "BOTH_SIDES": "questo mese il bene si compra o si vende, non entrambe le cose",
    "OWN_GOODS_ON_SALE": "hai già questo bene in vendita al mercato: lo ricompreresti pagando due volte il margine",
    "NO_MARKET_BUILDING": "il regno non ha ancora un mercato finito",
    "TRADE_CAPACITY": "i mercanti non possono trattare tanti lotti questo mese",
    "ONE_PER_REALM": "il regno ha già un mercato (o il suo cantiere)",
    # The territory (engine/territory.py).
    "NO_SPACE": "non c'è posto nella zona",
    "UNKNOWN_ZONE": "zona sconosciuta",
    "OUT_OF_MAP": "fuori dalla mappa",
    "NOT_OWNED": "fuori dalle terre del regno",
    "WRONG_TERRAIN": "terreno non adatto",
    "NO_FOREST": "non tocca il bosco",
    "OVERLAP": "sopra un altro edificio",
    "OUTSIDE_ZONE": "fuori dalla sua zona",
    "BAD_ZONES": "piano delle zone non valido",
    "UNKNOWN_BUILDING": "edificio sconosciuto",
    "NO_MAP": "questo regno non ha una mappa",
    "NO_LAND": "non ci sono abbastanza caselle adatte",
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
        where = f" ({order['zone']})" if order.get("zone") else ""
        return f"Costruire: {BUILDINGS.get(order.get('building'), order.get('building'))}{where}"
    if action == "set_zones":
        return f"Nuovo piano della città: {len(order.get('zones') or [])} zone"
    if action == "claim_tiles":
        if order.get("zone"):
            return f"Annettere {order.get('count')} caselle nella zona {order['zone']}"
        return (f"Annettere {order.get('count')} caselle di {TERRAINS.get(order.get('terrain'), order.get('terrain'))}"
                f" a {DIRECTIONS.get(order.get('direction'), order.get('direction'))}")
    if action == "fell_forest":
        where = f" a {DIRECTIONS.get(order['direction'], order['direction'])}" if order.get("direction") else ""
        return f"Abbattere {order.get('count')} caselle di bosco{where}"
    if action == "demolish":
        return f"Abbattere l'edificio n. {order.get('building_id')}"
    if action == "set_tax":
        return f"Tasse al {order.get('rate')}%"
    if action == "set_ration":
        return f"Razione {RATIONS.get(order.get('ration'), order.get('ration'))}"
    if action == "hold_feast":
        return f"Festa per il popolo: {order.get('gold')} oro"
    if action == "assign_workers":
        clearing = f", {order['clearing']} a dissodare" if order.get("clearing") else ""
        trade = f", {order['trade']} al mercato" if order.get("trade") else ""
        return (f"Lavoratori: {order.get('food')} nei campi, {order.get('wood')} nei boschi, "
                f"{order.get('stone')} nelle cave{clearing}{trade}")
    if action == "set_merchant_tax":
        return f"Tassa dei mercanti al {order.get('rate')}%"
    if action == "trade":
        verb = "Comprare" if order.get("side") == "buy" else "Vendere"
        return f"{verb} al mercato {lots_of(order.get('lots'), order.get('good'))}"
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
    if kind == "class_unrest_changed":
        who = CLASSES_IT.get(data.get("class"), data.get("class"))
        return (f"{who} passano da {UNREST.get(data.get('from'), data.get('from'))} "
                f"a {UNREST.get(data.get('to'), data.get('to'))}.")
    if kind == "merchant_tax":
        return f"I mercanti hanno pagato {data.get('gold')} oro di tassa sul commercio."
    if kind == "game_over":
        return GAME_OVER.get(data.get("reason"), f"Fine della partita: {data.get('reason')}.")
    if kind == "building_completed":
        if data.get("kind") in MASCULINE_BUILDINGS:
            return f"Completato un {BUILDINGS.get(data.get('kind'), data.get('kind'))}."
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
    if kind == "tile_cleared":
        return "Abbattuto un bosco: ora è pianura." if data.get("felled") else "Dissodata una nuova casella."
    if kind == "firewood_short":
        return f"Mancava la legna: il popolo ha patito il freddo ({data.get('missing')} legno su {data.get('needed')})."
    if kind == "stone_upkeep_short":
        return (f"Mancava la pietra per la manutenzione ({data.get('missing')} su {data.get('needed')}): "
                "gli edifici si sono consumati e hanno reso meno.")
    if kind == "trade_bought" and data.get("units"):
        return (f"Comprati al mercato {data['units']} di {GOODS_IT.get(data.get('good'), data.get('good'))}"
                f" (l'ultimo lotto era incompleto) per {data.get('gold')} oro.")
    if kind == "trade_bought":
        return f"Comprati al mercato {lots_of(data.get('lots'), data.get('good'))} per {data.get('gold')} oro."
    if kind == "trade_on_sale":
        return f"Messi in vendita al mercato {lots_of(data.get('lots'), data.get('good'))}."
    if kind == "trade_paid":
        return f"Il mercato ha pagato {data.get('gold')} oro per la merce venduta."
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
