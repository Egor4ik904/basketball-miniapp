# Быстрая сверка ESPN ID команд NBA — чтобы правильно сопоставить группы кубка.
import io, sys, httpx
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
client = httpx.Client(headers={"User-Agent":"Mozilla/5.0"}, timeout=20, trust_env=False)

r = client.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams")
teams = r.json()["sports"][0]["leagues"][0]["teams"]
print("ESPN ID -> команда:")
pairs = []
for item in teams:
    t = item["team"]
    pairs.append((int(t["id"]), t["displayName"], t.get("abbreviation")))
for tid, name, abbr in sorted(pairs):
    print(f"  {tid}: {name} ({abbr})")
print(f"\nвсего команд: {len(pairs)}")