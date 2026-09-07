# app/adapters/nbacup.py
# Адаптер NBA Cup (внутрисезонный турнир НБА, бывш. In-Season Tournament).
# Данные — из ESPN, как у NBA, но:
#   - матчи турнира выбираются из общего расписания по пометке в notes
#     ('NBA Cup - Group Play', '... Quarterfinals', 'Semifinals', 'Championship');
#   - таблиц групп ESPN простым способом не отдаёт, поэтому мы ВЫЧИСЛЯЕМ их
#     сами из результатов матчей, зная состав 6 групп (задан ниже вручную).
#
# Составы групп меняются каждый сезон — обновлять GROUPS при новом розыгрыше
# (публикуются в начале сезона на nba.com и в спортивных СМИ).

from datetime import date as _date, datetime as _datetime, timedelta

import httpx

from app import stages
from app.adapters import nba as nba_adapter   # переиспользуем команды/боксскор/составы

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

client = httpx.Client(
    headers={"User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)"},
    timeout=30,
    trust_env=False,
)

# Даты, в которые идёт турнир (групповой этап + плей-офф). Обновлять на новый
# розыгрыш. Групповой этап — конец октября..конец ноября, плей-офф — декабрь.
CUP_START = "2026-10-28"
CUP_END = "2026-12-15"

# Составы 6 групп по ESPN ID команд (сезон 2026/27). Обновлять ежегодно.
# ESPN ID: Atlanta1 Boston2 NewOrleans3 Chicago4 Cleveland5 Dallas6 Denver7
# Detroit8 GoldenState9 Houston10 Indiana11 LAClippers12 LALakers13 Miami14
# Milwaukee15 Minnesota16 Brooklyn17 NewYork18 Orlando19 Philadelphia20
# Phoenix21 Portland22 Sacramento23 SanAntonio24 OKC25 Utah26 Washington27
# Toronto28 Memphis29 Charlotte30
GROUPS = {
    "Восток, группа A": [8, 28, 19, 15, 17],      # Pistons, Raptors, Magic, Bucks, Nets
    "Восток, группа B": [18, 5, 20, 14, 11],      # Knicks, Cavaliers, 76ers, Heat, Pacers
    "Восток, группа C": [2, 1, 30, 4, 27],        # Celtics, Hawks, Hornets, Bulls, Wizards
    "Запад, группа A":  [7, 10, 21, 6, 26],       # Nuggets, Rockets, Suns, Mavericks, Jazz
    "Запад, группа B":  [25, 16, 12, 3, 29],      # Thunder, Timberwolves, Clippers, Pelicans, Grizzlies
    "Запад, группа C":  [24, 13, 22, 9, 23],      # Spurs, Lakers, Trail Blazers, Warriors, Kings
}

# обратный индекс: ESPN id команды -> название группы
_TEAM_GROUP = {}
for _gname, _ids in GROUPS.items():
    for _tid in _ids:
        _TEAM_GROUP[_tid] = _gname


# ===== переиспользуем у NBA то, что идентично =====
def fetch_teams() -> list[dict]:
    """Команды турнира — те же клубы NBA, но с префиксом nbacup:."""
    teams = []
    for t in nba_adapter.fetch_teams():
        # берём только те, что участвуют в кубке (все 30 участвуют)
        espn_id = int(t["id"].split(":")[1])
        t = dict(t)
        t["id"] = f"nbacup:{espn_id}"
        t["league_id"] = "nbacup"
        teams.append(t)
    return teams


def fetch_roster(team_id: str) -> list[dict]:
    """Состав команды — тот же, что в NBA (просто меняем префикс id)."""
    players = nba_adapter.fetch_roster(team_id)
    for p in players:
        p["id"] = p["id"].replace("nba:", "nbacup:", 1)
        p["team_id"] = p["team_id"].replace("nba:", "nbacup:", 1)
    return players


def fetch_boxscore(event_id: str) -> dict:
    """Box score матча — тот же, что в NBA."""
    box = nba_adapter.fetch_boxscore(event_id)
    box["game_id"] = f"nbacup:{event_id}"
    for team in box.get("teams", []):
        team["team_id"] = team["team_id"].replace("nba:", "nbacup:", 1)
    return box


def fetch_player_stats(athlete_id: str) -> dict | None:
    """Статистика игрока — та же, что в NBA (но статистики именно по кубку
    ESPN не выделяет; отдаём сезонную, как у NBA)."""
    st = nba_adapter.fetch_player_stats(athlete_id)
    if st:
        st["player_id"] = f"nbacup:{athlete_id}"
    return st


# ===== Матчи турнира — из расписания по пометке в notes =====
def _cup_stage_from_headline(headline: str):
    """'NBA Cup - Group Play' / '... Quarterfinals' / 'Semifinals' /
    'NBA Cup Championship' -> наша стадия."""
    h = (headline or "").lower()
    if "group" in h:
        return ("group", "Групповой этап")
    if "quarter" in h:
        return ("playoff", "1/4 финала")
    if "semi" in h:
        return ("playoff", "1/2 финала")
    if "championship" in h or "final" in h:
        return ("playoff", "Финал")
    return (None, None)


def _month_ranges(start_iso, end_iso):
    start = _date.fromisoformat(start_iso)
    end = _date.fromisoformat(end_iso)
    while start <= end:
        nxt = (_date(start.year + 1, 1, 1) if start.month == 12
               else _date(start.year, start.month + 1, 1))
        last = min(nxt - timedelta(days=1), end)
        yield start.strftime("%Y%m%d"), last.strftime("%Y%m%d")
        start = nxt


def fetch_season_games() -> list[dict]:
    """Все матчи NBA Cup: берём расписание за период турнира и оставляем
    только матчи с кубковой пометкой в notes."""
    games = []
    url = f"{ESPN_BASE}/scoreboard"
    for first, last in _month_ranges(CUP_START, CUP_END):
        try:
            r = client.get(url, params={"dates": f"{first}-{last}", "limit": 1000})
            r.raise_for_status()
            events = r.json().get("events", [])
        except Exception as e:
            print(f"[nbacup] {first}-{last}: матчи не получить: {e}")
            continue

        for event in events:
            comp = (event.get("competitions") or [{}])[0]
            notes = comp.get("notes") or []
            headline = notes[0].get("headline", "") if notes else ""
            stage_type, stage_label = _cup_stage_from_headline(headline)
            if not stage_type:
                continue                       # не кубковый матч — пропускаем

            parsed = _parse_cup_event(event, stage_type, stage_label, headline)
            if parsed:
                games.append(parsed)

    games.sort(key=lambda g: g["datetime"])
    print(f"[nbacup] матчи турнира загружены: {len(games)}")
    return games


def _parse_cup_event(event, stage_type, stage_label, headline):
    """Один кубковый матч в наш формат."""
    status_type = (event.get("status") or {}).get("type") or {}
    state = status_type.get("state")
    status = {"pre": "scheduled", "in": "live", "post": "final"}.get(state, state)

    comp = (event.get("competitions") or [{}])[0]
    home = away = None
    for c in (comp.get("competitors") or []):
        if c.get("homeAway") == "home":
            home = c
        elif c.get("homeAway") == "away":
            away = c
    if not home or not away:
        return None

    home_id = (home.get("team") or {}).get("id")
    away_id = (away.get("team") or {}).get("id")

    iso = event.get("date") or ""
    try:
        moment = _datetime.fromisoformat(iso.replace("Z", "+00:00"))
        game_date = (moment - timedelta(hours=6)).strftime("%Y-%m-%d")
    except Exception:
        game_date = iso[:10]

    st = event.get("status") or {}

    if stage_type == "group":
        # групповой матч — как «регулярка» турнира
        stage = stages._result(stages.REGULAR, stage_label)
    else:
        # плей-офф — одиночный матч (уникальный series_key, чтобы не серия)
        uniq = f"{headline}#{event.get('id')}"
        rnd = {"1/4 финала": 1, "1/2 финала": 2, "Финал": 4}.get(stage_label)
        stage = stages._result(stages.PLAYOFF, stage_label, series_key=uniq, series_round=rnd)

    return {
        "id": f"nbacup:{event.get('id')}",
        "league_id": "nbacup",
        "season": "2026",
        "game_date": game_date,
        "datetime": iso,
        "status": status,
        "home_team_id": f"nbacup:{home_id}",
        "away_team_id": f"nbacup:{away_id}",
        "home_score": home.get("score"),
        "away_score": away.get("score"),
        "period": st.get("period"),
        "clock": st.get("displayClock"),
        **stage,
    }


def fetch_games(date: str) -> list[dict]:
    target = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return [g for g in fetch_season_games() if g["game_date"] == target]


# ===== Таблицы групп — ВЫЧИСЛЯЕМ из результатов =====
def fetch_standings() -> list[dict]:
    """Таблицы 6 групп, посчитанные из сыгранных матчей группового этапа.
    Каждая строка помечена своей группой (conference) — фронт разложит по
    группам, как конференции."""
    # копим победы/поражения и разницу очков по каждой команде
    stats = {}   # espn_id -> {"w":..,"l":..,"diff":..}
    for tid in _TEAM_GROUP:
        stats[tid] = {"w": 0, "l": 0, "diff": 0}

    for g in fetch_season_games():
        if g.get("stage") != stages.REGULAR:      # только групповой этап
            continue
        if g.get("status") != "final":
            continue
        try:
            hs = int(g.get("home_score"))
            as_ = int(g.get("away_score"))
        except (TypeError, ValueError):
            continue
        h = int(g["home_team_id"].split(":")[1])
        a = int(g["away_team_id"].split(":")[1])
        if h not in stats or a not in stats:
            continue
        stats[h]["diff"] += hs - as_
        stats[a]["diff"] += as_ - hs
        if hs > as_:
            stats[h]["w"] += 1; stats[a]["l"] += 1
        else:
            stats[a]["w"] += 1; stats[h]["l"] += 1

    # формируем строки таблицы, сгруппированные и отсортированные внутри группы
    rows = []
    for gname, ids in GROUPS.items():
        group_rows = []
        for tid in ids:
            s = stats.get(tid, {"w": 0, "l": 0, "diff": 0})
            group_rows.append({
                "team_id": f"nbacup:{tid}",
                "league_id": "nbacup",
                "conference": gname,           # группа как «конференция»
                "wins": s["w"],
                "losses": s["l"],
                "win_pct": round(s["w"] / (s["w"] + s["l"]), 3) if (s["w"] + s["l"]) else None,
                "games_back": None,
                "streak": (f"+{s['diff']}" if s["diff"] > 0 else str(s["diff"])),  # разница очков
                "_diff": s["diff"],
            })
        # сортируем внутри группы: победы, потом разница очков
        group_rows.sort(key=lambda r: (-r["wins"], -r["_diff"]))
        for i, r in enumerate(group_rows, 1):
            r["rank"] = i
            del r["_diff"]
        rows += group_rows
    return rows


def clear_cache():
    """Кеша нет — данные каждый раз свежие из расписания."""
    return