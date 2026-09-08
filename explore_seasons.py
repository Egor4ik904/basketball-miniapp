# explore_cups_history.py
# Проверяем историю кубков:
#  1) NBA Cup — прошлые розыгрыши (2023, 2024): достаются ли матчи с пометкой Cup?
#  2) Winline Basket Cup — прошлый розыгрыш (52553) и его группы (52554/52555).

import io, sys
from datetime import date, timedelta
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
client = httpx.Client(headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 (compatible; BC/1.0)"},
                      timeout=25, trust_env=False)

def head(t):
    print("\n"+"="*72); print(t); print("="*72)

# ---------- NBA Cup: прошлые розыгрыши ----------
head("NBA Cup — прошлые розыгрыши (турнир идёт ноябрь-декабрь)")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
# NBA Cup: 2023 (ноя-дек 2023), 2024 (ноя-дек 2024), 2025 (ноя-дек 2025)
for year in [2023, 2024, 2025]:
    total_cup = 0
    stages_found = set()
    # сканируем ноябрь-декабрь этого года
    d = date(year, 11, 1)
    end = date(year, 12, 20)
    while d <= end:
        ds = d.strftime("%Y%m%d")
        try:
            r = client.get(f"{ESPN}/scoreboard", params={"dates":ds})
            for e in r.json().get("events",[]):
                comp = (e.get("competitions") or [{}])[0]
                notes = comp.get("notes") or []
                hl = notes[0].get("headline","") if notes else ""
                if "cup" in hl.lower() or "in-season" in hl.lower():
                    total_cup += 1
                    stages_found.add(hl)
        except Exception:
            pass
        d += timedelta(days=7)   # шаг неделю для скорости
    mark = "✅ есть" if total_cup > 5 else "⚠️ мало/нет"
    print(f"  {year}: матчей Cup ~{total_cup} (выборка) {mark}")
    if stages_found:
        print(f"       стадии: {stages_found}")

# ---------- Winline Cup: прошлый розыгрыш ----------
head("Winline Basket Cup — прошлый розыгрыш (52553) и группы")
API = "https://org.infobasket.su/Widget"
def to_iso(gd):
    try:
        d,m,y = gd.split("."); return f"{y}-{m}-{d}"
    except: return None

# календарь кубка
try:
    r = client.get(f"{API}/Calendar/52553", params={"format":"json"})
    games = r.json() or []
    dates = [to_iso(g.get("GameDate","")) for g in games if to_iso(g.get("GameDate",""))]
    played = sum(1 for g in games if g.get("ScoreA") or g.get("ScoreB"))
    print(f"  52553: матчей {len(games)}, сыграно {played}, даты {min(dates)}..{max(dates)}")
except Exception as e:
    print(f"  52553 ошибка: {e}")

# группы
for gid, gname in [(52554,"Группа A"),(52555,"Группа B")]:
    try:
        r = client.get(f"{API}/CompTeamResults/{gid}", params={"format":"json"})
        teams = [(t.get("CompTeamName") or {}).get("CompTeamShortNameRu") for t in r.json()]
        print(f"  {gname} ({gid}): {', '.join(t for t in teams if t)}")
    except Exception as e:
        print(f"  {gname} ошибка: {e}")

print("\n\nПришли вывод — поймём, есть ли история у NBA Cup и подтвердим Winline Cup.")