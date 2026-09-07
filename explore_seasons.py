# explore_vtb_season.py  (версия 8 — сканируем серию 55xxx)
# Номер сезона 55613 найден на сайте, но Calendar пока пуст (InfoBasket ещё
# не залил). Сканируем серию 55600..55660: вдруг матчи уже есть под этим или
# соседним номером. Ищем клубы ВТБ (ЦСКА, Зенit, УНИКС) и старт 25 сентября.

import io, sys
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (compatible; BC/1.0)"},
                      timeout=15, trust_env=False)

def to_iso(gd):
    try:
        d,m,y = gd.split("."); return f"{y}-{m}-{d}"
    except: return None

# главные клубы ВТБ — по ним опознаём главную лигу
VTB_CLUBS = {"ЦСКА","Зенит","УНИКС","Локомотив-К","Автодор","БЕТСИТИ ПАРМА",
             "Енисей","МБА","Самара","Уралмаш","Динамо"}

def check(sid):
    try:
        r = client.get(f"https://org.infobasket.su/Widget/Calendar/{sid}",
                       params={"format":"json"})
        if r.status_code != 200 or not r.content:
            return None
        games = r.json() or []
        if not games:
            return ("empty", 0, None, None, set())
        dates = [to_iso(g.get("GameDate","")) for g in games if to_iso(g.get("GameDate",""))]
        teams = set()
        for g in games:
            for k in ("ShortTeamNameAru","ShortTeamNameBru"):
                if g.get(k): teams.add(g[k])
        return ("has", len(games), min(dates) if dates else None,
                max(dates) if dates else None, teams)
    except Exception:
        return None

print("="*72)
print("Сканируем серию 55xxx на календарь нового сезона ВТБ")
print("="*72)

new_season_hits = []
empty_but_exist = []
for sid in range(55600, 55665):
    res = check(sid)
    if not res:
        continue
    status, count, dmin, dmax, teams = res
    if status == "empty":
        empty_but_exist.append(sid)
        continue
    # есть матчи — проверяем, наши ли клубы и осень 2026
    vtb_overlap = len(teams & VTB_CLUBS)
    is_2026 = (dmax or "") >= "2026-08"
    if vtb_overlap >= 3:
        mark = ""
        if is_2026:
            mark = "  ← ★★★ НОВЫЙ СЕЗОН ВТБ 2026/27"
            new_season_hits.append(sid)
        elif (dmin or "") >= "2025-09" and (dmax or "") <= "2026-07":
            mark = "  (старый сезон 2025/26)"
        print(f"  {sid}: матчей {count}, клубов {len(teams)}, {dmin}..{dmax}{mark}")
        if is_2026:
            print(f"       клубы: {', '.join(sorted(teams))}")

print("\n" + "="*72)
if new_season_hits:
    print(f"★ НАЙДЕН новый сезон под номером(ами): {new_season_hits}")
    print("Впишем в season.py!")
else:
    print("Календарь нового сезона в InfoBasket пока не залит (матчей нет).")
    print(f"Существующие, но пустые номера в серии: {empty_but_exist[:10]}")
    print("\nЭто значит: лига анонсировала расписание, но в техническую базу")
    print("InfoBasket (откуда берём данные) оно ещё не попало. Появится ближе")
    print("к старту (25 сентября). Проверим позже этим же скриптом.")