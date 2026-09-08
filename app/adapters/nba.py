# app/adapters/nba.py
# Адаптер лиги NBA: ходит в источники данных и приводит их
# к нашему единому формату (раздел 7 ТЗ).
# Умеет: команды, состав, матчи (за дату и за весь сезон), таблицу,
# статистику игрока, боксскор.

from datetime import date as _date, datetime as _datetime, timedelta

import httpx

from app import stages
from app import season as season_mod

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"

# Границы сезона для выкачки всех матчей.
# ПРИМЕЧАНИЕ: заданы вручную; в новом сезоне их нужно обновить.
SEASON_START = "2025-10-01"
SEASON_END = "2026-06-30"

# ESPN отдаёт время матча в UTC, а «игровой день» в Америке — местный.
# Матч в 22:30 по тихоокеанскому времени — это уже 05:30 UTC следующих суток,
# и без сдвига он уехал бы в календаре на день вперёд. Шесть часов назад
# возвращают такие матчи в правильный игровой день.
DAY_SHIFT_HOURS = 6

client = httpx.Client(
    headers={"User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)"},
    timeout=30,
    trust_env=False,
)

# Как ESPN называет состояние матча -> как называем мы.
STATUS_MAP = {"pre": "scheduled", "in": "live", "post": "final"}

# Как показатель статистики называется у ESPN -> как у нас.
STAT_MAP = {
    "gamesPlayed":   "games_played",
    "avgMinutes":    "minutes",
    "avgPoints":     "pts",
    "avgRebounds":   "reb",
    "avgAssists":    "ast",
    "avgSteals":     "stl",
    "avgBlocks":     "blk",
    "avgTurnovers":  "tov",
    "avgFouls":      "pf",
    "fieldGoalPct":  "fg_pct",
    "threePointPct": "fg3_pct",
    "freeThrowPct":  "ft_pct",
}


def fetch_teams() -> list[dict]:
    """Список команд NBA из ESPN в нашем едином формате."""
    url = f"{ESPN_BASE}/teams"
    response = client.get(url)
    response.raise_for_status()
    data = response.json()

    teams = []
    for item in data["sports"][0]["leagues"][0]["teams"]:
        t = item["team"]
        logo_url = None
        logos = t.get("logos")
        if logos:
            logo_url = logos[0].get("href")
        teams.append({
            "id": f"nba:{t['id']}",
            "league_id": "nba",
            "name": t.get("displayName"),
            "short_name": t.get("abbreviation"),
            "city": t.get("location"),
            "logo_url": logo_url,
        })
    return teams


def fetch_roster(team_id: str) -> list[dict]:
    """Состав (игроки) одной команды NBA из ESPN.
    team_id — числовой id команды у ESPN (например '13' — Lakers)."""
    url = f"{ESPN_BASE}/teams/{team_id}/roster"
    response = client.get(url)
    response.raise_for_status()
    data = response.json()

    raw = data.get("athletes", [])
    athletes = []
    for item in raw:
        if isinstance(item, dict) and "items" in item:
            athletes.extend(item["items"])
        else:
            athletes.append(item)

    players = []
    for a in athletes:
        position = a.get("position") or {}
        headshot = a.get("headshot") or {}
        players.append({
            "id": f"nba:{a.get('id')}",
            "team_id": f"nba:{team_id}",
            "name": a.get("fullName") or a.get("displayName"),
            "position": position.get("abbreviation"),
            "number": a.get("jersey"),
            "height": a.get("displayHeight"),
            "weight": a.get("displayWeight"),
            "birth_date": a.get("dateOfBirth"),
            "photo_url": headshot.get("href"),
        })
    return players


# ===== Матчи =====
def _parse_event(event: dict) -> dict | None:
    """Один матч из ответа scoreboard -> наш единый формат.
    None, если в ответе не хватает обязательных данных."""
    status_type = (event.get("status") or {}).get("type") or {}
    state = status_type.get("state")
    status = STATUS_MAP.get(state, state)

    competitions = event.get("competitions") or []
    if not competitions:
        return None
    comp = competitions[0]

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

    # Стадия: season.type (2 — регулярка, 3 — плей-офф, 5 — плей-ин)
    # плюс заголовок вроде «NBA Finals - Game 5» для названия круга.
    notes = comp.get("notes") or []
    headline = notes[0].get("headline") if notes else None
    season = event.get("season") or {}
    stage = stages.nba(season.get("type"), headline, home_id, away_id)

    iso = event.get("date") or ""
    try:
        moment = _datetime.fromisoformat(iso.replace("Z", "+00:00"))
        game_date = (moment - timedelta(hours=DAY_SHIFT_HOURS)).strftime("%Y-%m-%d")
    except Exception:
        game_date = iso[:10]

    st = event.get("status") or {}
    return {
        "id": f"nba:{event.get('id')}",
        "league_id": "nba",
        "season": str(season.get("year") or ""),
        "game_date": game_date,
        "datetime": iso,
        "status": status,
        "home_team_id": f"nba:{home_id}",
        "away_team_id": f"nba:{away_id}",
        "home_score": home.get("score"),
        "away_score": away.get("score"),
        "period": st.get("period"),
        "clock": st.get("displayClock"),
        **stage,
    }


def fetch_games(date: str) -> list[dict]:
    """Матчи NBA за указанную дату. date — в формате ГГГГММДД (напр. '20251225')."""
    response = client.get(f"{ESPN_BASE}/scoreboard", params={"dates": date})
    response.raise_for_status()

    games = []
    for event in response.json().get("events", []):
        parsed = _parse_event(event)
        if parsed:
            games.append(parsed)
    return games


def _month_ranges(start_iso: str, end_iso: str):
    """Режет период на календарные месяцы: ('20251001', '20251031'), ..."""
    start = _date.fromisoformat(start_iso)
    end = _date.fromisoformat(end_iso)
    while start <= end:
        nxt = (_date(start.year + 1, 1, 1) if start.month == 12
               else _date(start.year, start.month + 1, 1))
        last = min(nxt - timedelta(days=1), end)
        yield start.strftime("%Y%m%d"), last.strftime("%Y%m%d")
        start = nxt


def fetch_season_games(start: str = SEASON_START, end: str = SEASON_END) -> list[dict]:
    """Все матчи сезона NBA — по запросу на месяц (около девяти запросов к ESPN).
    ESPN понимает диапазон дат вида '20251001-20251031'.

    Кеша здесь нет намеренно: функцию зовёт прогрев один раз при старте, а
    рассылка уведомлений берёт ближайшие матчи из базы, а не отсюда. Держать
    весь сезон в памяти между вызовами незачем."""
    url = f"{ESPN_BASE}/scoreboard"
    games = []
    for first, last in _month_ranges(start, end):
        response = client.get(url, params={"dates": f"{first}-{last}", "limit": 1000})
        response.raise_for_status()
        events = response.json().get("events", [])
        for event in events:
            parsed = _parse_event(event)
            if parsed:
                games.append(parsed)
    games.sort(key=lambda g: g["datetime"])
    print(f"[nba] матчи сезона загружены: {len(games)}")
    return games


_standings_by_season: dict = {}


def list_seasons() -> list[dict]:
    """Сезоны для выбора в таблице (новые сверху). NBA-сезон обозначаем годом
    окончания: '2025-26' -> год 2026. Берём последние несколько."""
    try:
        cur = int(season_mod.nba()["year"]) if hasattr(season_mod, "nba") else 2026
    except Exception:
        cur = 2026
    seasons = []
    for year in range(cur, cur - 6, -1):     # текущий и 5 прошлых
        label = f"{year-1}-{str(year)[-2:]}"
        seasons.append({"code": str(year), "label": label})
    return seasons


def fetch_standings_for(season_code: str) -> list[dict]:
    """Турнирная таблица NBA за конкретный сезон (год окончания). Для выбора
    сезона. Кешируется по году."""
    if season_code in _standings_by_season:
        return _standings_by_season[season_code]

    rows = _parse_standings(params={"level": "3", "season": season_code})
    _standings_by_season[season_code] = rows
    return rows


def _parse_standings(params) -> list[dict]:
    """Общий разбор таблицы ESPN (используется и текущим сезоном, и прошлыми)."""
    response = client.get(ESPN_STANDINGS_URL, params=params)
    response.raise_for_status()
    data = response.json()

    def stat_value(by_name, key):
        return (by_name.get(key) or {}).get("value")

    def stat_display(by_name, key):
        return (by_name.get(key) or {}).get("displayValue")

    by_team = {}
    for conf in data.get("children", []):
        conf_name = conf.get("name")
        groups = []
        if isinstance(conf.get("standings"), dict):
            groups.append(conf["standings"])
        for div in (conf.get("children") or []):
            if isinstance(div.get("standings"), dict):
                groups.append(div["standings"])
        for group in groups:
            for entry in (group.get("entries") or []):
                team = entry.get("team") or {}
                team_id = f"nba:{team.get('id')}"
                by_name = {st.get("name"): st for st in (entry.get("stats") or [])}
                by_team[team_id] = {
                    "team_id": team_id,
                    "league_id": "nba",
                    "conference": conf_name,
                    "team_name": team.get("displayName"),
                    "team_short": team.get("abbreviation"),
                    "team_logo": (team.get("logos") or [{}])[0].get("href") if team.get("logos") else None,
                    "rank": stat_value(by_name, "playoffSeed"),
                    "wins": stat_value(by_name, "wins"),
                    "losses": stat_value(by_name, "losses"),
                    "win_pct": stat_value(by_name, "winPercent"),
                    "games_back": stat_display(by_name, "gamesBehind"),
                    "streak": stat_display(by_name, "streak"),
                }
    return list(by_team.values())


def fetch_playoff_for(season_code: str) -> list[dict]:
    """Матчи плей-офф NBA за конкретный сезон (год окончания, напр. '2025')
    — готовые строки для сетки. Плей-офф идёт апрель-июнь года окончания."""
    try:
        year = int(season_code)
    except ValueError:
        return []

    # имена/логотипы/посев команд этого сезона — из таблицы
    seeds = {}
    try:
        for row in _parse_standings(params={"level": "3", "season": season_code}):
            seeds[row["team_id"]] = {
                "name": row.get("team_name"), "short": row.get("team_short"),
                "logo": row.get("team_logo"), "seed": row.get("rank"),
                "conf": row.get("conference"),
            }
    except Exception as e:
        print(f"[nba] посевы сезона {season_code} не получены: {e}")

    # события плей-офф: апрель-июнь года окончания
    rows = []
    for first, last in [(f"{year}0415", f"{year}0430"),
                        (f"{year}0501", f"{year}0531"),
                        (f"{year}0601", f"{year}0625")]:
        try:
            r = client.get(f"{ESPN_BASE}/scoreboard",
                          params={"dates": f"{first}-{last}", "limit": 500})
            events = r.json().get("events", [])
        except Exception:
            continue
        for event in events:
            season = event.get("season") or {}
            if season.get("type") != 3:      # 3 = плей-офф
                continue
            g = _parse_event(event)
            if not g or g.get("stage") != "playoff":
                continue
            h = seeds.get(g["home_team_id"], {})
            a = seeds.get(g["away_team_id"], {})
            rows.append({
                "id": g["id"], "game_date": g["game_date"], "datetime": g["datetime"],
                "status": g["status"],
                "home_score": g["home_score"], "away_score": g["away_score"],
                "stage": g["stage"], "stage_label": g["stage_label"],
                "series_key": g["series_key"], "series_round": g["series_round"],
                "home_team_id": g["home_team_id"],
                "home_name": h.get("name"), "home_short": h.get("short"),
                "home_logo": h.get("logo"), "home_seed": h.get("seed"), "home_conf": h.get("conf"),
                "away_team_id": g["away_team_id"],
                "away_name": a.get("name"), "away_short": a.get("short"),
                "away_logo": a.get("logo"), "away_seed": a.get("seed"), "away_conf": a.get("conf"),
            })
    rows.sort(key=lambda r: (r["series_round"] or 0, r["series_key"] or "", r["datetime"]))
    return rows


def fetch_standings() -> list[dict]:
    """Турнирная таблица NBA из ESPN — по строке на команду.
    Дерево: конференции (children) -> дивизионы (children) -> standings.entries."""
    response = client.get(ESPN_STANDINGS_URL, params={"level": "3"})
    response.raise_for_status()
    data = response.json()

    def stat_value(by_name, key):
        return (by_name.get(key) or {}).get("value")

    def stat_display(by_name, key):
        return (by_name.get(key) or {}).get("displayValue")

    by_team = {}
    for conf in data.get("children", []):
        conf_name = conf.get("name")
        groups = []
        if isinstance(conf.get("standings"), dict):
            groups.append(conf["standings"])
        for div in (conf.get("children") or []):
            if isinstance(div.get("standings"), dict):
                groups.append(div["standings"])
        for group in groups:
            for entry in (group.get("entries") or []):
                team = entry.get("team") or {}
                team_id = f"nba:{team.get('id')}"
                by_name = {s.get("name"): s for s in (entry.get("stats") or [])}
                by_team[team_id] = {
                    "team_id": team_id,
                    "league_id": "nba",
                    "conference": conf_name,
                    "rank": stat_value(by_name, "playoffSeed"),
                    "wins": stat_value(by_name, "wins"),
                    "losses": stat_value(by_name, "losses"),
                    "win_pct": stat_value(by_name, "winPercent"),
                    "games_back": stat_display(by_name, "gamesBehind"),
                    "streak": stat_display(by_name, "streak"),
                }
    return list(by_team.values())


def fetch_player_stats(athlete_id: str) -> dict | None:
    """Средняя статистика игрока NBA за сезон из ESPN, переведённая на наши
    названия. athlete_id — числовой id игрока у ESPN. Если статистики нет — None."""
    url = f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/overview"
    response = client.get(url)
    response.raise_for_status()
    data = response.json()

    block = data.get("statistics") or {}
    names = block.get("names") or []
    splits = block.get("splits") or []
    if not names or not splits:
        return None

    # склеиваем названия показателей с их значениями и переводим на наши имена
    raw = dict(zip(names, (splits[0] or {}).get("stats") or []))
    result = {"player_id": f"nba:{athlete_id}"}
    for espn_name, our_name in STAT_MAP.items():
        result[our_name] = raw.get(espn_name)
    return result


def fetch_boxscore(event_id: str) -> dict:
    """Box score матча из ESPN: счёт по четвертям, командные итоги и
    статистика каждого игрока обеих команд (гости идут первыми)."""
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}"
    response = client.get(url)
    response.raise_for_status()
    data = response.json()

    box = data.get("boxscore") or {}

    # счёт, дом/гости и четверти — из header, по id команды
    header_by_team = {}
    comps = ((data.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []
    for c in comps:
        tid = (c.get("team") or {}).get("id")
        header_by_team[tid] = {
            "score": c.get("score"),
            "home_away": c.get("homeAway"),
            "quarters": [x.get("displayValue") for x in (c.get("linescores") or [])],
        }

    # командные итоги — из boxscore.teams, по id команды
    totals_by_team = {}
    for t in (box.get("teams") or []):
        tid = (t.get("team") or {}).get("id")
        totals_by_team[tid] = {s.get("name"): s.get("displayValue") for s in (t.get("statistics") or [])}

    # статистика игроков — из boxscore.players
    teams = []
    for group in (box.get("players") or []):
        team = group.get("team") or {}
        tid = team.get("id")
        block = (group.get("statistics") or [{}])[0]
        names = block.get("names") or []

        players = []
        for a in (block.get("athletes") or []):
            if a.get("didNotPlay"):
                continue                      # игрок не выходил — пропускаем
            line = dict(zip(names, a.get("stats") or []))
            players.append({
                "name": (a.get("athlete") or {}).get("displayName"),
                "starter": a.get("starter", False),
                "min": line.get("MIN"), "pts": line.get("PTS"), "reb": line.get("REB"),
                "ast": line.get("AST"), "stl": line.get("STL"), "blk": line.get("BLK"),
                "to": line.get("TO"), "fg": line.get("FG"), "fg3": line.get("3PT"),
                "ft": line.get("FT"), "pf": line.get("PF"), "plus_minus": line.get("+/-"),
            })

        h = header_by_team.get(tid, {})
        tot = totals_by_team.get(tid, {})
        teams.append({
            "team_id": f"nba:{tid}",
            "name": team.get("displayName"),
            "short_name": team.get("abbreviation"),
            "logo": team.get("logo"),
            "score": h.get("score"),
            "home_away": h.get("home_away"),
            "quarters": h.get("quarters", []),
            "players": players,
            "totals": {
                "fg": tot.get("fieldGoalsMade-fieldGoalsAttempted"),
                "fg_pct": tot.get("fieldGoalPct"),
                "fg3": tot.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"),
                "fg3_pct": tot.get("threePointFieldGoalPct"),
                "ft": tot.get("freeThrowsMade-freeThrowsAttempted"),
                "ft_pct": tot.get("freeThrowPct"),
                "reb": tot.get("totalRebounds"),
                "ast": tot.get("assists"),
                "stl": tot.get("steals"),
                "blk": tot.get("blocks"),
                "to": tot.get("totalTurnovers"),
            },
        })

    teams.sort(key=lambda t: 0 if t["home_away"] == "away" else 1)  # гости первыми
    return {"game_id": f"nba:{event_id}", "teams": teams}


def clear_cache():
    """У адаптера NBA кеша в памяти нет — данные живут в базе. Функция нужна
    для единообразия: планировщик зовёт clear_cache() у всех адаптеров."""
    return