# explore_playoff_history.py
# Проверяем, достаются ли матчи ПЛЕЙ-ОФФ прошлых сезонов по трём лигам.

import io, sys
from datetime import date, timedelta
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
client = httpx.Client(headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 (compatible; BC/1.0)"},
                      timeout=25, trust_env=False)

def head(t):
    print("\n"+"="*72); print(t); print("="*72)

# ---------- NBA: плей-офф прошлого сезона (апрель-июнь 2025) ----------
head("NBA — плей-офф прошлого сезона (2024/25, апрель-июнь 2025)")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
po_count = 0
for m in [("20250420","20250430"),("20250501","20250531"),("20250601","20250625")]:
    try:
        r = client.get(f"{ESPN}/scoreboard", params={"dates":f"{m[0]}-{m[1]}","limit":300})
        events = r.json().get("events",[])
        for e in events:
            comp = (e.get("competitions") or [{}])[0]
            notes = comp.get("notes") or []
            hl = notes[0].get("headline","") if notes else ""
            season = e.get("season") or {}
            # плей-офф: season.type == 3
            if season.get("type") == 3 or "playoff" in hl.lower() or "finals" in hl.lower():
                po_count += 1
    except Exception as ex:
        print(f"  ошибка: {ex}")
print(f"  матчей плей-офф найдено: {po_count}")
print(f"  -> {'✅ достаются' if po_count > 10 else '⚠️ мало/нет'}")

# ---------- Евролига: плей-офф E2025 ----------
head("Евролига — плей-офф прошлого сезона (E2025)")
EL = "https://api-live.euroleague.net"
try:
    r = client.get(f"{EL}/v1/results", params={"seasonCode":"E2025"})
    content = r.content.decode("utf-8", "replace")
    # плей-офф матчи помечены round=PO/FF/PI
    import re
    po = content.count('round="PO"') + content.count("'PO'")
    ff = content.count('round="FF"')
    # грубо: ищем game с плей-офф раундами
    po_games = len(re.findall(r'phaseType.{0,30}(Playoffs|Final Four)', content))
    print(f"  размер ответа: {len(content)}, упоминаний PO: {po}, FF: {ff}")
    print(f"  -> {'✅ данные есть' if len(content) > 3000 else '⚠️ проверить'}")
except Exception as ex:
    print(f"  ошибка: {ex}")

# ---------- ВТБ: плей-офф прошлого сезона (50714) ----------
head("ВТБ — плей-офф прошлого сезона (50714)")
API = "https://org.infobasket.su/Widget"
try:
    r = client.get(f"{API}/Calendar/50714", params={"format":"json"})
    games = r.json() or []
    # плей-офф: CompNameRu содержит финал/полуфинал
    po = [g for g in games if any(w in (g.get("CompNameRu") or "").lower()
          for w in ("финал","1/4","1/2","плей"))]
    print(f"  всего матчей: {len(games)}, плей-офф: {len(po)}")
    stages_set = set(g.get("CompNameRu") for g in po)
    print(f"  стадии плей-офф: {stages_set}")
    print(f"  -> {'✅ достаются' if len(po) > 3 else '⚠️ мало/нет'}")
except Exception as ex:
    print(f"  ошибка: {ex}")

print("\n\nПришли вывод — определим, у каких лиг плей-офф прошлых сезонов доступен.")