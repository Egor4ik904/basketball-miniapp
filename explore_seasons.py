# explore_vtb_full.py
# Разведка ВТБ для двух задач:
#  1) залит ли НОВЫЙ сезон 2026/27 (проверяем 55613 и соседей — есть ли матчи);
#  2) номера ПРОШЛЫХ сезонов ВТБ (для выбора сезона в таблице).

import io, sys
from datetime import datetime
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 (compatible; BC/1.0)"},
                      timeout=20, trust_env=False)

API = "https://org.infobasket.su/Widget"

def head(t):
    print("\n"+"="*72); print(t); print("="*72)

def to_iso(gd):
    try:
        d,m,y = gd.split("."); return f"{y}-{m}-{d}"
    except: return None

VTB_CLUBS = {"ЦСКА","Зенит","УНИКС","Локомотив-К","Автодор","БЕТСИТИ ПАРМА",
             "Енисей","МБА","Самара","Уралмаш","Динамо","ПАРМА","Пари НН","МБА-МАИ"}

def calendar_info(sid):
    """Матчи сезона по Calendar. Возвращает (кол-во, сыграно, даты, команды)."""
    try:
        r = client.get(f"{API}/Calendar/{sid}", params={"format":"json"})
        if r.status_code != 200 or not r.content:
            return None
        games = r.json() or []
        if not games:
            return ("empty",)
        dates = [to_iso(g.get("GameDate","")) for g in games if to_iso(g.get("GameDate",""))]
        played = sum(1 for g in games if g.get("ScoreA") or g.get("ScoreB"))
        teams = set()
        for g in games:
            for k in ("ShortTeamNameAru","ShortTeamNameBru"):
                if g.get(k): teams.add(g[k])
        return ("has", len(games), played, min(dates) if dates else "?",
                max(dates) if dates else "?", teams)
    except Exception:
        return None

def standings_info(comp):
    """Таблица по CompTeamResults. Возвращает список команд или None."""
    try:
        r = client.get(f"{API}/CompTeamResults/{comp}", params={"format":"json"})
        if r.status_code != 200 or not r.content:
            return None
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        teams = [(t.get("CompTeamName") or {}).get("CompTeamShortNameRu") for t in data]
        return [t for t in teams if t]
    except Exception:
        return None

# ---------- Задача 1: новый сезон 2026/27 ----------
head("1. Новый сезон ВТБ 2026/27 — залит ли (проверяем 55613 и соседей)")
for sid in [55613, 55614, 55615, 55616, 55617, 55618, 55619, 55620]:
    info = calendar_info(sid)
    if not info:
        continue
    if info[0] == "empty":
        # календарь пуст, но проверим таблицу — вдруг команды уже есть
        teams = standings_info(sid)
        if teams and len(set(teams) & VTB_CLUBS) >= 3:
            print(f"  comp={sid}: календарь пуст, но таблица есть — команд {len(teams)}: {', '.join(teams[:6])}")
        continue
    _, cnt, played, dmin, dmax, teams = info
    overlap = len(teams & VTB_CLUBS)
    if overlap >= 3:
        new = dmax >= "2026-08"
        mark = "  ← ★ НОВЫЙ СЕЗОН 2026/27" if new else ""
        print(f"  sid={sid}: матчей {cnt} (сыграно {played}), {dmin}..{dmax}{mark}")
        print(f"       команды: {', '.join(sorted(teams))}")

# ---------- Задача 2: прошлые сезоны ВТБ ----------
head("2. Прошлые сезоны ВТБ — ищем номера (для выбора сезона)")
print("Известно: 50720 = сезон 2025/26. Ищем более ранние (таблицы с клубами ВТБ).\n")
# сканируем диапазоны, где могут быть прошлые сезоны
found_seasons = []
for comp in list(range(50600, 50725)) + list(range(49000, 49100)):
    teams = standings_info(comp)
    if not teams:
        continue
    overlap = len(set(teams) & VTB_CLUBS)
    # полноценный сезон ВТБ: 10-13 команд, много клубов ВТБ
    if overlap >= 5 and 8 <= len(teams) <= 14:
        print(f"  comp={comp}: команд {len(teams)}, клубов ВТБ {overlap}: {', '.join(teams[:8])}")
        found_seasons.append(comp)

print(f"\nНайдено кандидатов на сезоны ВТБ: {found_seasons}")
print("\nПришли вывод — определим, залит ли новый сезон и какие прошлые доступны.")