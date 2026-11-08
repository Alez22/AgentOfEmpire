"""@brief A game where every realm is played by the automatic sovereign
(server/sovereign/auto.py), through the HTTP API of a running server.

Usage (the server must run with the current code):
  python3 lab/auto_game.py new <seed> <months> [names...]   new game, e.g. new 0 12 Aurelia Brenna Corvara
  python3 lab/auto_game.py go <game_id> <months>            play more months of a game

With real models a month costs about what a council meeting costs per realm,
plus one round per directive. Prints, per month and realm, the sovereign's
reasons and the stores at the start of the next month.
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
TIMEOUT_S = 900  # a meeting with real models takes up to a few minutes


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        return {"error": error.code, "detail": error.read().decode()[:500]}


def stores_line(realm_id: int) -> str:
    s = call("GET", f"/realms/{realm_id}/state")
    end = f" | {s['game_over']}" if s.get("game_over") else ""
    return (f"food {s['food']} wood {s['wood']} stone {s['stone']} gold {s['gold']} | tax {s['tax_rate']}"
            f" ration {s['ration']} unrest {s['unrest']}{end}")


def play(game_id: int, months: int) -> None:
    for _ in range(months):
        game = call("GET", f"/games/{game_id}")
        if game["open_turn"] is None:
            print("the game is over")
            return
        print(f"\n== turn {game['open_turn']}")
        for realm in game["realms"]:
            result = call("POST", f"/realms/{realm['id']}/sovereign/auto")
            print(f"  {realm['name']}:")
            for line in result.get("lines", [json.dumps(result)]) or ["(plan approved as it is)"]:
                print(f"    {line}")
        print("  ", call("POST", f"/games/{game_id}/turns/resolve"))
        for realm in game["realms"]:
            print(f"  {realm['name']:<10} {stores_line(realm['id'])}")


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[1] not in ("new", "go"):
        print(__doc__)
        return 2
    if sys.argv[1] == "new":
        names = sys.argv[4:] or ["Aurelia", "Brenna", "Corvara"]
        game = call("POST", "/games", {"seed": int(sys.argv[2]), "realm_names": names})
        if "error" in game:
            print(game)
            return 1
        print(f"game {game['id']}: {', '.join(r['name'] + ' ' + str(r['id']) for r in game['realms'])}")
        play(game["id"], int(sys.argv[3]))
    else:
        play(int(sys.argv[2]), int(sys.argv[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
