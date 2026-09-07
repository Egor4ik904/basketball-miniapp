# explore_schedule.py
# Проверяем расписание для двух лиг:
#  1) ВТБ — залит ли уже календарь нового сезона (перепроверка).
#  2) Евролига — сколько будущих матчей в новом сезоне E2026 и их даты
#     (чтобы добавить расписание нового сезона, не трогая таблицу старого).

import io, sys, re
from datetime import datetime
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (compatible; BC/1.0)"},
                      timeout=20, trust_env=False)

def head(t):
    print("\n" + "="*72); print(t); print("="*72)

# ---------- ВТБ ----------
head("ВТБ — залит ли календарь нового сезона 2026/27")
def to_iso(gd):
    try:
        d,m,y = gd.split("."); return f"{y}-{m}-{d}"
    except: return None

VTB_CLUBS = {"ЦСКА","Зенит","УНИКС","Локомотив-К","Автодор","БЕТСИТИ ПАРМА",
             "Енисей","МБА","Самара","Уралмаш","Динамо","ПАРМА"}

def vtb_check(sid):
    try:
        r = client.get(f"https://org.infobasket.su/Widget/Calendar/{sid}",
                       params={"format":"json"})
        if r.status_code != 200 or not r.content:
            return None
        games = r.json() or []
        if not games:
            return ("empty",)
        dates = [to_iso(g.get("GameDate","")) for g in games if to_iso(g.get("GameDate",""))]
        teams = set()
        for g in games:
            for k in ("ShortTeamNameAru","ShortTeamNameBru"):
                if g.get(k): teams.add(g[k])
        return ("has", len(games), min(dates) if dates else "?",
                max(dates) if dates else "?", teams)
    except Exception:
        return None

# перепроверяем найденный номер и серию вокруг
vtb_found = []
for sid in list(range(55600, 55665)) + [55613]:
    res = vtb_check(sid)
    if not res or res[0] == "empty":
        continue
    _, count, dmin, dmax, teams = res
    if len(teams & VTB_CLUBS) >= 3 and dmax >= "2026-08":
        print(f"  ★ season_id={sid}: матчей {count}, {dmin}..{dmax}")
        print(f"     клубы: {', '.join(sorted(teams))}")
        vtb_found.append(sid)

if vtb_found:
    print(f"\n  ✅ ВТБ: календарь нового сезона ЗАЛИТ под номером(ами) {vtb_found}")
else:
    print("  ⏳ ВТБ: календарь нового сезона пока НЕ залит (матчей нет).")

# ---------- Евролига ----------
head("Евролига — расписание нового сезона E2026")
EL = "https://api-live.euroleague.net"
today = datetime.now().strftime("%Y-%m-%d")

for code in ["E2026"]:
    try:
        r = client.get(f"{EL}/v2/competitions/E/seasons/{code}/games")
        data = r.json()
        games = data.get("data") if isinstance(data, dict) else data
        games = games or []
        future = []
        for g in games:
            d = (g.get("date") or g.get("startDate") or "")[:10]
            if d >= today:
                h = g.get("home") or g.get("homeTeam") or g.get("local") or "?"
                a = g.get("away") or g.get("awayTeam") or g.get("road") or "?"
                future.append((d, h, a))
        print(f"  {code}: всего матчей {len(games)}, будущих {len(future)}")
        if future:
            future.sort()
            print(f"  первые 5 будущих матчей:")
            for d, h, a in future[:5]:
                print(f"     {d}: {h} — {a}")
            print(f"  диапазон: {future[0][0]} .. {future[-1][0]}")
            print("  -> ✅ расписание нового сезона ЕСТЬ, можно добавить")
    except Exception as e:
        print(f"  {code}: ошибка {e}")

print("\n\nПришли вывод — по нему решим: добавляем расписание Евролиги нового")
print("сезона, и готов ли ВТБ.")