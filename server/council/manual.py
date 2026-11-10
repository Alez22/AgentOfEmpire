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
from engine.territory import is_hex
from server.council.map_text import shape_text

SEASONS = ("winter", "spring", "summer", "autumn")
SEASONS_IT = {"winter": "inverno", "spring": "primavera", "summer": "estate", "autumn": "autunno"}
PRODUCT = {"food": "food", "wood": "wood", "stone": "stone"}
PRODUCT_IT = {"food": "cibo", "wood": "legno", "stone": "pietra"}
BUILDING_IT = {"farm": "Fattoria", "sawmill": "Segheria", "quarry": "Cava", "house": "Casa", "market": "Mercato",
               "watchtower": "Torre di guardia"}


def _season_pcts(config: Config) -> dict[str, int]:
    economy = config.economy
    return {"winter": economy.farm_winter_pct, "spring": economy.farm_spring_pct,
            "summer": economy.farm_summer_pct, "autumn": economy.farm_autumn_pct}


def _yield_text(config: Config, spec) -> str:
    """@brief The yield per worker, or (with land levels) only that it depends
    on the land: the levels are a secret the council finds out from its
    production (docs/DESIGN.md, "Land levels")."""
    if config.levels is not None:
        return (f"each worker yields {PRODUCT[spec.sector]} every month; how much depends on the realm's land "
                "(your briefing shows what this month will yield)")
    return f"each worker yields {spec.output_per_worker} {PRODUCT[spec.sector]} a month"


def _yield_text_it(config: Config, spec) -> str:
    if config.levels is not None:
        return (f"ogni lavoratore produce {PRODUCT_IT[spec.sector]} ogni mese; quanto, dipende dalla terra del "
                "regno, e lo si scopre dal raccolto")
    return f"ogni lavoratore produce {spec.output_per_worker} {PRODUCT_IT[spec.sector]} al mese"


def _buildings(config: Config) -> list:
    """@brief The building kinds of this game. The market building only where
    the market needs one (village block A), the watchtower only where there
    are bandits (block B+C): elsewhere they are not a rule."""
    needs_market = config.market is not None and config.market.needs_building
    return [(kind, spec) for kind, spec in config.buildings.items()
            if (spec.sector != "trade" or needs_market) and (kind != "watchtower" or config.bandits is not None)]


def _taxed_adults(config: Config) -> str:
    """@brief Who pays the ordinary tax: every adult, or all but the merchants."""
    if config.market is not None and config.market.needs_building:
        return "adults who are not merchants"
    return "adults"


def _taxed_adults_it(config: Config) -> str:
    if config.market is not None and config.market.needs_building:
        return "adulti che non sono mercanti"
    return "adulti"


def _gold_text(config: Config) -> str:
    if config.market is not None:
        return ("Gold also buys food, wood and stone at the common market, and selling them there brings gold "
                "(see Market below).")
    return "There is no market and no trade: gold cannot buy food, wood or stone."


def prompt_text(config: Config) -> str:
    """@brief The manual for the counsellors' system prompts (English)."""
    economy, unrest = config.economy, config.unrest
    seasons = ", ".join(f"{s} {p}%" for s, p in _season_pcts(config).items())
    where = ("each stands on the map, see Territory below" if config.map is not None
             else "each uses one free tile")
    lines = ["The manual of the realm (how things work; the numbers of this month are in your briefing):",
             f"Buildings ({where}; a site produces nothing until finished):"]
    for kind, spec in _buildings(config):
        cost = f"costs wood {spec.wood}, stone {spec.stone}, gold {spec.gold}; built in {spec.build_turns} months"
        if spec.sector == "trade":
            # Village block A: the merchants produce no goods, they handle lots.
            line = (f"- {kind}: {cost}; only one per realm, in a market zone; {spec.jobs} jobs for merchants, "
                    f"each handles {config.market.lots_per_merchant} lots a month at the common market. "
                    "Without it the realm cannot trade.")
        elif kind == "watchtower":
            line = (f"- {kind}: {cost}; only one per realm, in a watch zone at the village's gate; no jobs. "
                    "When it is finished the Gastaldo joins the council, and only then can the realm keep "
                    "guards (a militia) against bandits.")
        elif spec.jobs:
            line = f"- {kind}: {cost}; {spec.jobs} jobs; {_yield_text(config, spec)}"
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
        f"Taxes and gold: gold a month = {_taxed_adults(config)} x tax rate / {economy.tax_divisor} (maximum rate "
        f"{economy.max_tax_rate}%). {_gold_text(config)} Gold pays for houses, feasts and upkeep.",
        "Feast: it costs the gold given and lifts the people's spirits at once, for a while; repeated the "
        "month after it is worth half. It brings no food.",
        "The people: heavy taxes, a short ration, hunger, deaths and full houses weigh on them; a generous "
        "ration, feasts and relief from a burden cheer them. Their mood changes slowly. They decide how hard "
        "they work and whether families have children, and may petition the crown.",
        f"Unrest: after {unrest.protest_turns} months of deep discontent there are protests (no effect on "
        f"production); after {unrest.strike_turns} a strike (all production {unrest.strike_output_pct - 100}%); "
        f"after {unrest.revolt_turns} a revolt, the end of the realm.",
    ]
    if config.needs is not None:
        lines += _needs_lines(config)
    if config.market is not None:
        lines += _market_lines(config)
    if config.map is not None:
        lines += _territory_lines(config)
    if config.bandits is not None:
        lines += _bandits_lines(config)
    return "\n".join(lines) + "\n"


def _bandits_lines(config: Config) -> list[str]:
    """@brief Flight, bandits and the militia (village block B+C), for the prompts.
    The pool's size is never told: nobody in the game knows it."""
    rules = config.bandits
    lines = [
        "Bandits and arrivals:" if config.migration is not None else "Bandits:",
        f"- After {rules.flee_turns} months of deep discontent (the count that leads to protests) a class starts "
        f"to flee: every month about {rules.flee_adult_pct}% of its adults leave for the woods, the peasants with "
        f"{rules.flee_child_pct}% of the children; the elders stay. The merchants flee by their own discontent. "
        "Those who leave become bandits, in a world whose bandits nobody can count.",
        f"- Bandits raid in bands of about {rules.party_size}, choosing the realms where most food and wood lie "
        f"exposed and the guard is weakest. Each raider carries away up to {rules.carry} units, food first, "
        "then wood. Bandits eat what they take; without loot they go hungry and scatter.",
        f"- Guards (the militia) exist only once the watchtower is finished and the Gastaldo sits on the council: "
        f"each guard stops {rules.repel_per_guard} raiders, enough guards drive a band off, fewer cut its loot. "
        "Guards are adults taken from work before the Architect assigns the others, and they produce nothing. "
        f"The Gastaldo's salary is {rules.gastaldo_salary} gold a month.",
    ]
    if config.migration is not None:
        lines += _arrivals_lines(config)
    return lines


def _arrivals_lines(config: Config) -> list[str]:
    """@brief The doors and acceptance (village block B+C, stage 2), for the prompts."""
    rules = config.migration
    return [
        f"- Every month about {rules.seek_pct}% of the wanderers look for a home. They go only to a realm whose "
        f"people are calm (no unrest), with food for at least {rules.min_food_months} month(s) of eating and "
        "free beds; they settle as peasants, free for the Architect's work from the next month, their "
        "children as children. Who settles is a bandit less in the woods.",
        "- The doors (the Gastaldo's order, only with the watchtower; without it every realm is at normal): "
        "closed takes nobody; normal takes as many as the empty jobs, never beyond the free beds; open fills "
        f"the free beds, beyond the jobs too. Closed doors hold only with at least {rules.closed_min_guards} "
        "guards, with fewer they count as normal.",
        f"- Of the raiders the guards stop, {rules.keep_normal_pct}% stay with normal doors and "
        f"{rules.keep_open_pct}% with open doors, as far as the free beds go; closed doors drive them all off.",
        f"- When food is short (less than {rules.scarce_food_months} months of eating) or there is no empty "
        "job, the people grumble against the newcomers: the more arrive at once against the population, "
        "the louder they grumble. With enough food and work for all, nobody grumbles.",
    ]


def _month_names(months: list[int]) -> str:
    names = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December")
    return ", ".join(names[m - 1] for m in months)


def _needs_lines(config: Config) -> list[str]:
    needs = config.needs
    return [
        f"Firewood: in {_month_names(needs.firewood_months)} the realm burns 1 wood for every "
        f"{needs.firewood_people} people each month. Without enough wood the people are cold and suffer at once.",
        f"Stone upkeep: every month each {'' if needs.stone_upkeep_buildings == 1 else str(needs.stone_upkeep_buildings) + ' '}"
        f"active building{'' if needs.stone_upkeep_buildings == 1 else 's'} needs 1 stone. Without enough stone "
        "the buildings wear and all production falls that month.",
    ]


def _market_lines(config: Config) -> list[str]:
    """@brief The market rules (engine/market.py), for the prompts."""
    m = config.market
    lines = [
        f"Market: one warehouse shared by every realm of the world. Food, wood and stone are traded in lots of "
        f"{m.lot_units}, only by the Treasurer's trade orders. Trades run at the start of the month, before every "
        "other order, so what is bought can be used the same month.",
        f"- Buying costs the price + {m.margin_pct}%, selling pays the price - {m.margin_pct}%. A realm sells "
        "OR buys a good in a month, not both.",
        "- Goods sold leave the stores at once and wait in the warehouse; the seller is paid only when a buyer "
        "takes them, oldest first, maybe months later. They cannot be taken back. Food there rots like in the "
        "granaries.",
        "- A purchase gets only what the warehouse holds: when the buyers ask more, they share what there is and "
        "may get fewer lots.",
        f"- Prices move by {m.step_pct}% a month: up when more was asked than there was, down when goods on sale "
        "pile up unsold.",
        "- Everyone sees the prices, the stock and the month's totals; nobody sees who sold or bought.",
    ]
    if m.no_buying_own_goods:
        lines.append("- A realm that has a good waiting on sale cannot buy that good: it would buy back its own "
                     "goods and pay the margin twice.")
    if m.short_last_lot:
        lines.append(f"- When the warehouse holds less than {m.lot_units} of a good (food lost to rot), it sells "
                     "as one short lot, paid only for what it holds.")
    if m.needs_building:
        spec = config.buildings["market"]
        lines += [
            f"- A realm trades only once its market building is finished ({spec.wood} wood, {spec.build_turns} "
            "months, one per realm, in a market zone). Before that it knows nothing of the prices.",
            f"- The merchants (adults assigned to the market, up to its {spec.jobs} places) handle the lots: "
            f"{m.lots_per_merchant} lots a month each, buying and selling together. Discontented "
            "merchants handle fewer, and on strike none.",
            f"- The merchants pay their own tax, set by the Treasurer (0-{m.max_merchant_tax}%), on the gold value "
            "of the month's trades, instead of the ordinary tax. Like the peasants, they feel their own burdens and "
            "have their own unrest: the merchants' tax, an idle market while goods wait in the warehouse, hunger and a short "
            "ration weigh on them; a busy market cheers them. Their unrest stops at the strike.",
        ]
    return lines


def _footprints(config: Config) -> str:
    return ", ".join(f"{kind} {shape_text(config, kind)} on {spec.terrain}"
                     + (" touching a forest of the realm" if spec.needs_forest else "")
                     for kind, spec in config.buildings.items())


def _shape_rule(config: Config) -> str:
    """@brief How a building's place is given, and the square's shape."""
    if is_hex(config):
        return ("The map is made of hexes (odd rows half a hex to the east, 6 neighbours each). A building is "
                "given by its anchor hex: the farm's centre, the first hex of the others; the square is a "
                "rhombus of 4 hexes.")
    return (f"A building is given by its anchor, its top-left tile; the square is {config.map.square_size} x "
            f"{config.map.square_size}.")


def _territory_lines(config: Config) -> list[str]:
    """@brief The territory rules (docs/DESIGN.md, "Territory"), for the prompts."""
    m = config.map
    return [
        f"Territory: the realm owns tiles of plain, forest, hill and river. Footprints: {_footprints(config)}. "
        f"{_shape_rule(config)} Nothing is built on river or forest, and buildings never overlap.",
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
    for kind, spec in _buildings(config):
        cost = (f"Costa {spec.wood} legno, {spec.stone} pietra, {spec.gold} oro; "
                f"si costruisce in {spec.build_turns} mesi.")
        if spec.sector == "trade":
            text = (f"{cost} Uno solo per regno, in una zona del mercato; {spec.jobs} posti per i mercanti, ognuno "
                    f"tratta {config.market.lots_per_merchant} lotti al mese al mercato comune. Senza, il regno "
                    "non commercia.")
        elif kind == "watchtower":
            text = (f"{cost} Una sola per regno, in una zona di guardia alla porta del villaggio; nessun posto di "
                    "lavoro. Quando è finita arriva il Gastaldo, e solo allora il regno può tenere delle guardie "
                    "(una milizia) contro i briganti.")
        elif spec.jobs:
            text = f"{cost} {spec.jobs} posti di lavoro; {_yield_text_it(config, spec)}"
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
            f"Oro al mese = {_taxed_adults_it(config)} × aliquota / {economy.tax_divisor} (aliquota massima "
            f"{economy.max_tax_rate}%).",
            ("L'oro compra anche cibo, legno e pietra al mercato, e venderli lì porta oro (vedi Mercato)."
             if config.market is not None else
             "Non c'è mercato né commercio: l'oro non compra cibo, legno o pietra.")
            + " Serve per case, feste e manutenzione.",
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
    ] + ([_needs_section(config)] if config.needs is not None else []) \
      + ([_market_section(config)] if config.market is not None else []) \
      + ([_territory_section(config)] if config.map is not None else []) \
      + ([_bandits_section(config)] if config.bandits is not None else [])


def _bandits_section(config: Config) -> dict:
    """@brief Flight, bandits and the militia for the sovereign's page (Italian)."""
    rules = config.bandits
    notes = [
        f"Dopo {rules.flee_turns} mesi di scontento profondo (lo stesso conto che porta alle proteste) una classe "
        f"comincia a fuggire: ogni mese circa il {rules.flee_adult_pct}% dei suoi adulti parte per i boschi, i "
        f"contadini con l'{rules.flee_child_pct}% dei bambini; gli anziani restano. I mercanti fuggono per il loro "
        "scontento. Chi parte diventa brigante, e nessuno sa quanti briganti ci siano al mondo.",
        f"I briganti assaltano in bande di circa {rules.party_size}, scegliendo i regni dove c'è più cibo e legno "
        f"in vista e la guardia è più debole. Ogni brigante porta via fino a {rules.carry} unità, prima il cibo, "
        "poi il legno. I briganti mangiano ciò che rubano; senza bottino fanno la fame e si disperdono.",
        f"Le guardie (la milizia) esistono solo con la torre di guardia finita e il Gastaldo nel consiglio: ogni "
        f"guardia ferma {rules.repel_per_guard} briganti; abbastanza guardie respingono la banda, meno guardie "
        "riducono il bottino. Le guardie sono adulti tolti al lavoro prima che l'Architetta assegni gli altri, e "
        f"non producono nulla. Il Gastaldo costa {rules.gastaldo_salary} oro al mese di salario.",
    ]
    if config.migration is None:
        return {"title": "Briganti", "entries": [], "notes": notes}
    return {"title": "Briganti e arrivi", "entries": [], "notes": notes + _arrivals_notes(config)}


def _arrivals_notes(config: Config) -> list[str]:
    """@brief The doors and acceptance for the sovereign's page (Italian)."""
    rules = config.migration
    return [
        f"Ogni mese circa il {rules.seek_pct}% dei vagabondi cerca casa. Va solo in un regno con il popolo "
        f"calmo (nessun disordine), cibo per almeno {rules.min_food_months} mese e letti liberi; si stabilisce "
        "come contadino, libero per il lavoro dall'Architetta dal mese dopo, i bambini come bambini. Chi si "
        "stabilisce è un brigante in meno nei boschi.",
        "Le porte (ordine del Gastaldo, solo con la torre; senza torre ogni regno ha le porte normali): chiuse "
        "non entra nessuno; normali entrano quanti sono i posti di lavoro vuoti, mai oltre i letti liberi; "
        f"aperte si riempiono i letti liberi, anche oltre il lavoro. Le porte chiuse tengono solo con almeno "
        f"{rules.closed_min_guards} guardie, con meno contano come normali.",
        f"Dei briganti fermati dalle guardie restano il {rules.keep_normal_pct}% con le porte normali e il "
        f"{rules.keep_open_pct}% con le porte aperte, finché ci sono letti liberi; le porte chiuse li "
        "cacciano tutti.",
        f"Quando il cibo scarseggia (meno di {rules.scarce_food_months} mesi) o non c'è lavoro libero, il popolo "
        "mormora contro i nuovi venuti: più ne arrivano insieme rispetto alla popolazione, più forte mormora. "
        "Con cibo e lavoro per tutti nessuno mormora.",
    ]


MONTHS_IT = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
             "ottobre", "novembre", "dicembre")


def _needs_section(config: Config) -> dict:
    needs = config.needs
    months = ", ".join(MONTHS_IT[m - 1] for m in needs.firewood_months)
    per = "ogni edificio attivo" if needs.stone_upkeep_buildings == 1 else f"ogni {needs.stone_upkeep_buildings} edifici attivi"
    return {"title": "Legna e pietra", "entries": [], "notes": [
        f"Legna: nei mesi di {months} il regno brucia 1 legno ogni {needs.firewood_people} abitanti al mese. "
        "Se il legno non basta, il popolo patisce il freddo e ne soffre subito.",
        f"Manutenzione in pietra: ogni mese {per} vuole 1 pietra. Se la pietra non basta, gli edifici si "
        "consumano e quel mese tutta la produzione cala.",
    ]}


def _market_section(config: Config) -> dict:
    m = config.market
    notes = [
        f"Un solo magazzino per tutti i regni del mondo. Cibo, legno e pietra si scambiano a lotti di "
        f"{m.lot_units}, solo con gli ordini del Tesoriere. Gli scambi avvengono all'inizio del mese, prima di "
        "ogni altro ordine: ciò che si compra si usa subito.",
        f"Chi compra paga il prezzo più il {m.margin_pct}%, chi vende riceve il prezzo meno il {m.margin_pct}%. "
        "In un mese un bene si compra oppure si vende, non entrambe le cose.",
        "La merce venduta lascia subito i magazzini del regno e aspetta nel magazzino comune: chi vende è "
        "pagato solo quando qualcuno la compra, prima la più vecchia, anche mesi dopo. Non si può ritirare. "
        "Il cibo lì marcisce come nei granai.",
        "Un acquisto prende solo ciò che il magazzino ha: se si chiede più di quanto c'è, i compratori si "
        "dividono ciò che c'è e possono ricevere meno lotti.",
        f"I prezzi si muovono del {m.step_pct}% al mese: salgono se si è chiesto più di quanto c'era, scendono "
        "se la merce resta invenduta.",
        "Tutti vedono prezzi, scorte e totali del mese; nessuno vede chi ha venduto o comprato.",
    ]
    if m.no_buying_own_goods:
        notes.append("Chi ha un bene in vendita non può comprarne: ricomprerebbe la propria merce pagando due "
                     "volte il margine.")
    if m.short_last_lot:
        notes.append(f"Se nel magazzino resta meno di {m.lot_units} di un bene (il cibo marcisce), si vende come "
                     "un lotto incompleto e si paga solo ciò che contiene.")
    if m.needs_building:
        spec = config.buildings["market"]
        notes += [
            f"Il regno commercia solo quando il suo mercato è finito ({spec.wood} legno, {spec.build_turns} mesi, "
            "uno per regno, nella zona del mercato). Prima non conosce nemmeno i prezzi.",
            f"I mercanti (adulti assegnati al mercato, fino ai suoi {spec.jobs} posti) trattano i lotti: "
            f"{m.lots_per_merchant} al mese ciascuno, tra acquisti e vendite. Se sono scontenti ne trattano di "
            "meno, in sciopero nessuno.",
            f"I mercanti pagano una tassa loro, decisa dal Tesoriere (0-{m.max_merchant_tax}%), sul valore in oro "
            "degli scambi del mese, al posto della tassa ordinaria. Come i contadini hanno un loro umore e i loro "
            "disordini: pesano la loro tassa, un mercato fermo mentre c'è merce in vendita, la fame e la razione "
            "ridotta; un mercato che lavora li rallegra. I loro disordini si fermano allo sciopero.",
        ]
    return {"title": "Mercato", "entries": [], "notes": notes}


TERRAIN_IT = {"plain": "pianura", "hill": "collina", "forest": "bosco"}


# Footprints in Italian on the hex grid (engine/config.toml hex_steps).
HEX_SIZES_IT = {"farm": "7 esagoni (un centro e i suoi 6 vicini)", "sawmill": "2 esagoni affiancati",
                "quarry": "4 esagoni a rombo", "house": "1 esagono", "market": "2 esagoni affiancati",
                "watchtower": "1 esagono"}


def _size_it(config: Config, kind: str) -> str:
    if is_hex(config):
        return HEX_SIZES_IT.get(kind, f"{len(config.buildings[kind].hex_steps) + 1} esagoni")
    spec = config.buildings[kind]
    return f"{spec.width}×{spec.height}"


def _territory_section(config: Config) -> dict:
    """@brief The territory rules for the sovereign's page (Italian)."""
    m = config.map
    hex_map = is_hex(config)
    sizes = ", ".join(f"{BUILDING_IT.get(kind, kind).lower()} {_size_it(config, kind)} in "
                      f"{TERRAIN_IT.get(spec.terrain, spec.terrain)}" + (" accanto al bosco" if spec.needs_forest else "")
                      for kind, spec in config.buildings.items())
    square = "un rombo di 4 esagoni" if hex_map else f"{m.square_size}×{m.square_size}"
    grid = "La mappa è fatta di esagoni: ognuno ha 6 vicini. " if hex_map else ""
    return {"title": "Territorio", "entries": [], "notes": [
        f"{grid}Il regno possiede caselle di pianura, bosco, collina e fiume. Ingombri: {sizes}; la piazza "
        f"{square}. Sul fiume e sul bosco non si costruisce.",
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
