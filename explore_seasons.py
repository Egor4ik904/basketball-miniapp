# explore_cups.py (v4 — ищем номера групп кубка и проясняем розыгрыш)
# Таблица 52553 отдаёт 8 команд без деления на группы. Проверяем: есть ли
# у групп А и Б отдельные номера (сканируем рядом с 52553), и стартовал ли
# новый розыгрыш (даты матчей).

import io, sys, json
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(headers={"Accept":"application/json",
                               "User-Agent":"Mozilla/5.0 (compatible; BC/1.0)"},
                      timeout=15, trust_env=False)

API = "https://org.infobasket.su/Widget"

def head(t):
    print("\n"+"="*72); print(t); print("="*72)

def to_iso(gd):
    try:
        d,m,y = gd.split("."); return f"{y}-{m}-{d}"
    except: return None

# 1) Сканируем номера рядом с 52553 — ищем группы (по 4 команды) и др. стадии
head("Сканируем 52540-52580: таблицы с командами кубка")
CUP_TEAMS = {"ЦСКА","Зенит","УНИКС","Локомотив-Кубань","ПАРМА","Уралмаш",
             "Игокеа м:тел","Мега Супербет","ФМП","Бетсити Парма"}

def check_standings(cid):
    try:
        r = client.get(f"{API}/CompTeamResults/{cid}", params={"format":"json"})
        if r.status_code != 200 or not r.content:
            return None
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        teams = []
        for t in data:
            cn = t.get("CompTeamName") or {}
            nm = cn.get("CompTeamShortNameRu")
            if nm: teams.append(nm)
        return teams
    except Exception:
        return None

for cid in range(52540, 52581):
    teams = check_standings(cid)
    if not teams:
        continue
    overlap = len(set(teams) & CUP_TEAMS)
    if overlap >= 3:
        marker = ""
        if len(teams) == 4:
            marker = "  ← ГРУППА (4 команды)!"
        elif len(teams) == 8:
            marker = "  ← вся таблица кубка (8)"
        print(f"  comp={cid}: команд {len(teams)} — {', '.join(teams)}{marker}")

# 2) Проясняем розыгрыш: даты матчей у 52553
head("Календарь 52553 — какие даты (новый розыгрыш или прошлый?)")
try:
    r = client.get(f"{API}/Calendar/52553", params={"format":"json"})
    games = r.json() if r.status_code==200 and r.content else []
    dates = [to_iso(g.get("GameDate","")) for g in games if to_iso(g.get("GameDate",""))]
    if dates:
        played = sum(1 for g in games if g.get("ScoreA") or g.get("ScoreB"))
        print(f"  матчей: {len(games)}, сыграно: {played}, даты: {min(dates)}..{max(dates)}")
        # первый несыгранный матч
        for g in sorted(games, key=lambda x: to_iso(x.get("GameDate","")) or ""):
            if not (g.get("ScoreA") or g.get("ScoreB")):
                print(f"  первый несыгранный: {g.get('GameDate')} "
                      f"{g.get('ShortTeamNameAru')} — {g.get('ShortTeamNameBru')} "
                      f"[{g.get('GameNumber')}]")
                break
except Exception as e:
    print(f"  ошибка: {e}")

print("\n\nПришли вывод — поймём, есть ли отдельные номера групп и стартовал ли кубок.")