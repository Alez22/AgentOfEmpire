"""@brief The manual of the realm: how its elements work, written from the
game's own config so it can never say something the engine does not do.

Two renderings of the same facts: English for the counsellors' prompts,
Italian for the sovereign's page. Mood formulas are left out on purpose
(the council and the sovereign know the people only from the square): the
manual says what weighs on the people, never how much.

Why: in the playtests counsellors kept guessing how things work ("a farm
creates two jobs", "a half-filled farm stays empty", "gold buys grain", "a
feast brings food"); each guess had been patched with a prompt rule.
"""

from engine.config import Config

SEASONS = ("winter", "spring", "summer", "autumn")
SEASONS_IT = {"winter": "inverno", "spring": "primavera", "summer": "estate", "autumn": "autunno"}
PRODUCT = {"food": "food", "wood": "wood", "stone": "stone"}
PRODUCT_IT = {"food": "cibo", "wood": "legno", "stone": "pietra"}
BUILDING_IT = {"farm": "Fattoria", "sawmill": "Segheria", "quarry": "Cava", "house": "Casa"}


def _season_pcts(config: Config) -> dict[str, int]:
    economy = config.economy
    return {"winter": economy.farm_winter_pct, "spring": economy.farm_spring_pct,
            "summer": economy.farm_summer_pct, "autumn": economy.farm_autumn_pct}


def prompt_text(config: Config) -> str:
    """@brief The manual for the counsellors' system prompts (English)."""
    economy, unrest = config.economy, config.unrest
    seasons = ", ".join(f"{s} {p}%" for s, p in _season_pcts(config).items())
    where = ("each stands on the map, see Territory below" if config.map is not None
             else "each uses one free tile")
    lines = ["The manual of the realm (how things work; the numbers of this month are in your briefing):",
             f"Buildings ({where}; a site produces nothing until finished):"]
    for kind, spec in config.buildings.items():
        cost = f"costs wood {spec.wood}, stone {spec.stone}, gold {spec.gold}; built in {spec.build_turns} months"
        if spec.jobs:
            line = (f"- {kind}: {cost}; {spec.jobs} jobs; each worker yields {spec.output_per_worker} "
                    f"{PRODUCT[spec.sector]} a month")
            if spec.sector == "food":
                line += f" at the season's yield ({seasons})"
            # A fact only: "a half-filled building already pays" was read as "build
            # another" (bench 2026-11-07); when to build is the Architect's craft.
            line += ". It yields for every worker in it, even when not all its jobs are filled."
        else:
            line = f"- {kind}: {cost}; houses {spec.housing} people; no jobs."
        lines.append(line)
    lines += [
        f"- Every building costs {economy.upkeep_gold_per_building} gold of upkeep a month; if the gold is not "
        f"enough, buildings yield {economy.unpaid_upkeep_output_pct}% that month.",
        "- The counsellors are paid a salary in gold every month, after the upkeep; when the gold is short "
        "they are not paid, and they know it.",
        "Workers: only adults work. Workers beyond a sector's jobs produce nothing. Workers can be moved "
        "between sectors any month, and the move counts that same month. Children grow into adults over the "
        "years; a new adult is free until assigned.",
        f"Food: each month a child eats {economy.food_per_child}, an adult {economy.food_per_adult}, an elder "
        f"{economy.food_per_elder} at the normal ration; the reduced ration is {economy.ration_reduced_pct}%, "
        f"the abundant {economy.ration_abundant_pct}%. After eating, {economy.food_spoilage_pct}% of the stored "
        "food rots. If the food runs out there is hunger: people die, and the people suffer at once.",
        "Births need food and free places in the houses: none while houses are full or there is hunger.",
        f"Taxes and gold: gold a month = adults x tax rate / {economy.tax_divisor} (maximum rate "
        f"{economy.max_tax_rate}%). There is no market and no trade: gold cannot buy food, wood or stone. "
        "Gold pays for houses, feasts and upkeep.",
        "Feast: it costs the gold given and lifts the people's spirits at once, for a while; repeated the "
        "month after it is worth half. It brings no food.",
        "The people: heavy taxes, a short ration, hunger, deaths and full houses weigh on them; a generous "
        "ration, feasts and relief from a burden cheer them. Their mood changes slowly. They decide how hard "
        "they work and whether families have children, and may petition the crown.",
        f"Unrest: after {unrest.protest_turns} months of deep discontent there are protests (no effect on "
        f"production); after {unrest.strike_turns} a strike (all production {unrest.strike_output_pct - 100}%); "
        f"after {unrest.revolt_turns} a revolt, the end of the realm.",
    ]
    if config.map is not None:
        lines += _territory_lines(config)
    return "\n".join(lines) + "\n"


def _footprints(config: Config) -> str:
    return ", ".join(f"{kind} {spec.width} x {spec.height} on {spec.terrain}"
                     + (" touching a forest of the realm" if spec.needs_forest else "")
                     for kind, spec in config.buildings.items())


def _territory_lines(config: Config) -> list[str]:
    """@brief The territory rules (docs/DESIGN.md, "Territory"), for the prompts."""
    m = config.map
    return [
        f"Territory: the realm owns tiles of plain, forest, hill and river. Footprints: {_footprints(config)}; "
        f"the square is {m.square_size} x {m.square_size}. Nothing is built on river or forest, and buildings "
        "never overlap.",
        "- The town plan divides the land into zones (fields, center, houses, workshops, reserve); a building "
        "stands only inside a zone of its kind, houses also in the center. The plan can be redrawn.",
        f"- Claiming: a bordering tile costs {m.claim_base_gold} gold, one more for every {m.claim_step_tiles} "
        "tiles owned beyond the core. The gold goes to the land fund. A claimed plain or hill is wild until "
        f"cleared: {m.clear_work_plain} worker-months for a plain, {m.clear_work_hill} for a hill. A claimed "
        "forest stands and belongs to the realm at once.",
        f"- Felling a forest of the realm takes {m.clear_work_forest} worker-months and gives "
        f"{m.fell_wood_per_work} wood for each; the tile becomes plain. A sawmill produces only while it "
        "touches a forest of the realm.",
        f"- Demolishing a building costs {m.demolish_gold} gold, gives back {m.demolish_refund_pct}% of its "
        "wood and stone and frees its tiles at once; its workers lose their jobs.",
    ]


def page_sections(config: Config) -> list[dict]:
    """@brief The same manual for the sovereign's page (Italian), by section."""
    economy, unrest = config.economy, config.unrest
    seasons = ", ".join(f"{SEASONS_IT[s]} {p}%" for s, p in _season_pcts(config).items())
    buildings = []
    for kind, spec in config.buildings.items():
        cost = (f"Costa {spec.wood} legno, {spec.stone} pietra, {spec.gold} oro; "
                f"si costruisce in {spec.build_turns} mesi.")
        if spec.jobs:
            text = (f"{cost} {spec.jobs} posti di lavoro; ogni lavoratore produce {spec.output_per_worker} "
                    f"{PRODUCT_IT[spec.sector]} al mese")
            text += f", secondo la stagione ({seasons})." if spec.sector == "food" else "."
            text += " Rende per ogni lavoratore, anche se non è piena."
        else:
            text = f"{cost} Ospita {spec.housing} persone; nessun posto di lavoro."
        buildings.append({"name": BUILDING_IT.get(kind, kind), "text": text})
    return [
        {"title": "Edifici", "entries": buildings, "notes": [
            ("Ogni edificio occupa le sue caselle sulla mappa (vedi Territorio); un cantiere non produce nulla "
             "finché non è finito." if config.map is not None else
             "Ogni edificio occupa una casella libera; un cantiere non produce nulla finché non è finito."),
            f"Ogni edificio costa {economy.upkeep_gold_per_building} oro di manutenzione al mese; se l'oro "
            f"non basta, quel mese gli edifici rendono il {economy.unpaid_upkeep_output_pct}%.",
            "I consiglieri ricevono ogni mese un salario in oro, pagato dopo la manutenzione: se l'oro non "
            "basta restano senza paga, e lo sanno.",
        ]},
        {"title": "Lavoratori", "entries": [], "notes": [
            "Lavorano solo gli adulti. Chi supera i posti di un settore non produce nulla.",
            "I lavoratori si possono spostare da un settore all'altro ogni mese, con effetto nello stesso mese.",
            "I bambini diventano adulti con gli anni; un adulto nuovo resta libero finché non viene assegnato.",
        ]},
        {"title": "Cibo e granaio", "entries": [], "notes": [
            f"Ogni mese, a razione normale, un bambino mangia {economy.food_per_child}, un adulto "
            f"{economy.food_per_adult}, un anziano {economy.food_per_elder}. La razione ridotta è il "
            f"{economy.ration_reduced_pct}%, quella abbondante il {economy.ration_abundant_pct}%.",
            f"Dopo i pasti marcisce il {economy.food_spoilage_pct}% del cibo in granaio.",
            "Se il cibo finisce arriva la fame: muore gente, e il popolo ne soffre subito.",
            "Le nascite vogliono cibo e posti liberi nelle case: con le case piene o con la fame non nasce nessuno.",
        ]},
        {"title": "Tasse e oro", "entries": [], "notes": [
            f"Oro al mese = adulti × aliquota / {economy.tax_divisor} (aliquota massima {economy.max_tax_rate}%).",
            "Non c'è mercato né commercio: l'oro non compra cibo, legno o pietra. Serve per case, feste e manutenzione.",
            "Una festa costa l'oro che le dai e solleva subito il popolo, per un po'; ripetuta il mese dopo vale "
            "la metà. Non porta cibo.",
        ]},
        {"title": "Il popolo", "entries": [], "notes": [
            "Pesano sul popolo tasse alte, razione scarsa, fame, lutti e case piene; lo sollevano una razione "
            "abbondante, le feste e il sollievo da un peso. L'umore cambia piano, e lo conosci solo dalla piazza.",
            "Il popolo decide quanto impegno mettere nel lavoro e se fare figli, e può rivolgere suppliche alla corona.",
            f"Malcontento: dopo {unrest.protest_turns} mesi di scontento profondo arrivano le proteste (senza "
            f"effetto sulla produzione), dopo {unrest.strike_turns} lo sciopero (tutta la produzione "
            f"{unrest.strike_output_pct - 100}%), dopo {unrest.revolt_turns} la rivolta, la fine del regno.",
        ]},
    ] + ([_territory_section(config)] if config.map is not None else [])


TERRAIN_IT = {"plain": "pianura", "hill": "collina", "forest": "bosco"}


def _territory_section(config: Config) -> dict:
    """@brief The territory rules for the sovereign's page (Italian)."""
    m = config.map
    sizes = ", ".join(f"{BUILDING_IT.get(kind, kind).lower()} {spec.width}×{spec.height} in "
                      f"{TERRAIN_IT.get(spec.terrain, spec.terrain)}" + (" accanto al bosco" if spec.needs_forest else "")
                      for kind, spec in config.buildings.items())
    return {"title": "Territorio", "entries": [], "notes": [
        f"Il regno possiede caselle di pianura, bosco, collina e fiume. Ingombri: {sizes}; la piazza "
        f"{m.square_size}×{m.square_size}. Sul fiume e sul bosco non si costruisce.",
        "Il piano della città divide la terra in zone (campi, centro, case, botteghe, riserva): un edificio "
        "sta solo in una zona del suo tipo, le case anche nel centro. Lo disegna l'Architetta.",
        f"Annettere una casella confinante costa {m.claim_base_gold} oro, uno in più ogni {m.claim_step_tiles} "
        "caselle oltre il nucleo; l'oro va al fondo delle terre. Pianura e collina annesse vanno dissodate "
        f"({m.clear_work_plain} e {m.clear_work_hill} mesi-lavoratore); il bosco annesso resta in piedi.",
        f"Abbattere un bosco del regno richiede {m.clear_work_forest} mesi-lavoratore e dà {m.fell_wood_per_work} "
        "legno per ciascuno; la casella diventa pianura. Una segheria produce solo se tocca un bosco del regno.",
        f"Abbattere un edificio costa {m.demolish_gold} oro e restituisce il {m.demolish_refund_pct}% del suo "
        "legno e della sua pietra.",
    ]}
