"""@brief What the "Mercato" page shows (mockup approved 2026-11-08).

Pure functions: the route loads the data, this module turns it into plain
values for the template. Only public facts of the market (prices, stock,
totals) and this realm's own goods and trades: never who else sold or
bought, and never the realm's land levels.
"""

from engine.config import Config
from engine.market import GOODS, MarketState, buy_price, sell_price, stock
from engine.state import GameState
from engine.turn import firewood_needed, stone_upkeep
from server.ui import labels

HISTORY_MONTHS = 6
OF_THE_GOOD = {"food": "del cibo", "wood": "del legno", "stone": "della pietra"}
BAR_MIN_PX, BAR_SPAN_PX = 8, 22  # bar heights of the price history
TRENDS = {
    "up": ("sale: si chiede più di quanto c'è", "up"),
    "down": ("scende: resta invenduto", "down"),
    "same": ("stabile", "same"),
}


def _trend(history: list[tuple[int, MarketState]], good: str) -> str:
    if len(history) < 2:
        return "same"
    before, now = history[-2][1].goods[good].price, history[-1][1].goods[good].price
    return "up" if now > before else "down" if now < before else "same"


def _bars(history: list[tuple[int, MarketState]], config: Config, good: str) -> list[dict]:
    prices = [market.goods[good].price for _, market in history]
    top = max(prices) or 1
    return [{"height": BAR_MIN_PX + BAR_SPAN_PX * price // top, "price": price,
             "now": index == len(prices) - 1} for index, price in enumerate(prices)]


def _good_row(history: list[tuple[int, MarketState]], config: Config, good: str) -> dict:
    market = history[-1][1]
    book = market.goods[good]
    words, kind = TRENDS[_trend(history, good)]
    bars = _bars(history, config, good)
    return {
        "name": labels.GOODS_IT[good].capitalize(),
        "buy": buy_price(market, config, good),
        "sell": sell_price(market, config, good),
        "stock": stock(book),
        "last_bought": book.last_bought,
        "last_sold": book.last_sold,
        "trend_words": words,
        "trend": kind,
        "bars": bars,
        "bars_label": (f"Prezzo {OF_THE_GOOD[good]} negli ultimi {len(bars)} mesi: "
                       + ", ".join(str(b["price"]) for b in bars)),
        "first_month": labels.month_name(history[0][0]),
        "last_month": labels.month_name(history[-1][0]),
    }


def _waiting(market: MarketState, config: Config, realm_key: str) -> list[dict]:
    """@brief This realm's goods on sale and what they would fetch today."""
    lot = config.market.lot_units
    rows = []
    for good in GOODS:
        units = sum(c.units for c in market.goods[good].queue if c.seller == realm_key)
        if units:
            rows.append({"name": labels.GOODS_IT[good].capitalize(), "units": units,
                         "worth": units * sell_price(market, config, good) // lot})
    return rows


def _trade_proposals(plan: dict | None, market: MarketState, config: Config) -> list[dict]:
    """@brief The Treasurer's trades in this month's plan, with their gold."""
    rows = []
    for item in (plan or {}).get("plan", []):
        order = item["order"]
        if order.get("action") != "trade":
            continue
        if order["side"] == "buy":
            gold = f"−{order['lots'] * buy_price(market, config, order['good'])} oro"
        else:
            gold = f"+{order['lots'] * sell_price(market, config, order['good'])} oro, quando si vende"
        rows.append({"label": labels.order_label(order), "gold": gold})
    return rows


def _needs_lines(state: GameState, config: Config) -> list[str]:
    needs = config.needs
    if needs is None:
        return []
    months = needs.firewood_months
    now = firewood_needed(state, config)
    return [
        f"Legna da ardere: {state.population() // needs.firewood_people} al mese da "
        f"{labels.MONTHS[months[0] - 1]} a {labels.MONTHS[months[-1] - 1]} "
        + (f"(questo mese {now})." if now else "(questo mese nulla)."),
        f"Manutenzione: {stone_upkeep(state, config)} pietra al mese per gli edifici.",
    ]


def market_page(history: list[tuple[int, MarketState]], state: GameState, config: Config, realm_key: str,
                plan: dict | None, last_events: list[dict]) -> dict:
    """@brief Everything the page shows.
    @param history (turn, market at the start of that turn), oldest first,
           the last one this turn's; at most HISTORY_MONTHS.
    @param plan The latest summary payload of the open turn, or None.
    @param last_events This realm's events of the previous month.
    """
    market = history[-1][1]
    return {
        "lot": config.market.lot_units,
        "goods": [_good_row(history, config, good) for good in GOODS],
        "waiting": _waiting(market, config, realm_key),
        "stores": [("Cibo", state.food), ("Legno", state.wood), ("Pietra", state.stone), ("Oro", state.gold)],
        "needs": _needs_lines(state, config),
        "proposals": _trade_proposals(plan, market, config),
        "met": plan is not None,
        "last_month": [labels.event_label(e["kind"], e["data"]) for e in last_events
                       if e["kind"].startswith("trade_")],
    }
