# app/adapters/euroleague.py
# Адаптер лиги Евролига (api-live.euroleague.net) через httpx с trust_env=False.
# Умеет: команды, таблицу, матчи (за дату и за весь сезон), боксскор,
# составы, статистику игрока.
#
# Сезон больше не зашит в код — его определяет app/season.py.

import httpx
import xmltodict
from datetime import datetime

from app import season as season_mod
from app import stages

API = "https://api-live.euroleague.net"
COMP = "E"

client = httpx.Client(
    headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)",
    },
    timeout=30,
    trust_env=False,
)


def _season() -> dict:
    return season_mod.euroleague()


def _season_code() -> str:
    """Сезон для матчей, таблицы и статистики."""
    return _season()["code"]


def _roster_season_code() -> str:
    """Сезон для составов: может быть новее, чем сезон матчей (клубы
    заявляют игроков раньше, чем публикуется календарь)."""
    return _season()["roster_code"]


# ===== маленькие помощники =====
def _num(v):
    return v if v is not None else 0


def _pct(made, att):
    made, att = _num(made), _num(att)
    return str(round(made / att * 100)) if att else None


def _i(v):
    try:
        return str(int(round(float(v))))
    except Exception:
        return None


def _f1(v):
    try:
        return str(round(float(v), 1))
    except Exception:
        return None


def _strip_pct(s):
    if not s:
        return None
    return str(s).replace("%", "").strip()


def _fix_name(name):
    """'SHORTS, TJ' -> 'Tj Shorts'."""
    if not name:
        return name
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return name.title()


# ===== Команды и таблица (basicstandings) =====
_standings_cache = None


def _standings_data() -> dict:
    global _standings_cache
    if _standings_cache is None:
        code = _season_code()
        round_no = _season()["standings_round"]
        url = (f"{API}/v3/competitions/{COMP}/seasons/{code}"
               f"/rounds/{round_no}/basicstandings")
        response = client.get(url)
        response.raise_for_status()
        _standings_cache = response.json()
    return _standings_cache


_clubs_cache: dict = {}


def _clubs(season_code: str) -> list:
    """Список клубов сезона. Появляется, как только объявлены участники, —
    задолго до расписания."""
    if season_code not in _clubs_cache:
        url = f"{API}/v2/competitions/{COMP}/seasons/{season_code}/clubs"
        try:
            r = client.get(url)
            _clubs_cache[season_code] = ((r.json() or {}).get("data") or []
                                         if r.status_code == 200 else [])
        except Exception:
            _clubs_cache[season_code] = []
    return _clubs_cache[season_code]


def _club_to_team(club: dict, season_code: str) -> dict:
    return {
        "id": f"euroleague:{club.get('code')}",
        "league_id": "euroleague",
        "season": season_code,
        "name": club.get("name"),
        "short_name": club.get("abbreviatedName"),
        "city": club.get("city"),
        "logo_url": (club.get("images") or {}).get("crest"),
    }


def fetch_teams() -> list[dict]:
    """Команды лиги.

    Основной список — участники нового сезона (их объявляют задолго до
    календаря). Плюс добавляем клубы сезона матчей, которых в новом нет:
    без них в таблице прошлого сезона у выбывших команд пропали бы
    название и логотип. Показывать их на вкладке «Команды» не будем —
    отсечём по сезону.
    """
    squad_code = _roster_season_code()
    data_code = _season_code()

    teams = []
    seen = set()
    for club in _clubs(squad_code):
        teams.append(_club_to_team(club, squad_code))
        seen.add(club.get("code"))

    if data_code != squad_code:
        for club in _clubs(data_code):
            if club.get("code") not in seen:
                teams.append(_club_to_team(club, data_code))

    # Если список клубов почему-то не отдался, берём команды из таблицы —
    # так было раньше, пусть останется страховкой.
    if not teams:
        for t in _standings_data().get("teams", []):
            club = t.get("club") or {}
            teams.append(_club_to_team(club, data_code))

    return teams


def fetch_standings() -> list[dict]:
    standings = []
    for t in _standings_data().get("teams", []):
        club = t.get("club") or {}
        wp = t.get("winPercentage")
        win_pct = None
        if wp:
            try:
                win_pct = round(float(str(wp).replace("%", "")) / 100, 3)
            except Exception:
                win_pct = None
        standings.append({
            "team_id": f"euroleague:{club.get('code')}",
            "league_id": "euroleague",
            "conference": None,
            "rank": t.get("position"),
            "wins": t.get("gamesWon"),
            "losses": t.get("gamesLost"),
            "win_pct": win_pct,
            "games_back": None,
            "streak": "".join(t.get("last5Form") or []),
        })
    return standings


_teams_by_code = None


def _team_info(code: str) -> dict:
    global _teams_by_code
    if _teams_by_code is None:
        _teams_by_code = {}
        for t in _standings_data().get("teams", []):
            club = t.get("club") or {}
            _teams_by_code[club.get("code")] = {
                "name": club.get("name"),
                "short_name": club.get("abbreviatedName"),
                "logo": (club.get("images") or {}).get("crest"),
            }
    return _teams_by_code.get(code, {})


# ===== Матчи (v1/results, XML) =====
_results_cache = None


def _get_results() -> list:
    global _results_cache
    if _results_cache is None:
        r = client.get(f"{API}/v1/results", params={"seasonCode": _season_code()})
        r.raise_for_status()
        data = xmltodict.parse(r.content)
        games = (data.get("results") or {}).get("game") or []
        if isinstance(games, dict):
            games = [games]
        _results_cache = games
    return _results_cache


def _euro_to_iso(euro_date: str):
    try:
        return datetime.strptime(euro_date, "%b %d, %Y").strftime("%Y-%m-%d")
    except Exception:
        return None


def fetch_season_games() -> list[dict]:
    """Все матчи сезона одним махом. Запрос к источнику уже закеширован
    в _get_results(), так что второй раз он не выполняется.

    Стадия берётся из полей round ('RS' / 'PI' / 'PO' / 'FF') и group
    ('Regular Season', 'PLAYOFF A'..'PLAYOFF D', 'SEMIFINAL A', ...).
    """
    code = _season_code()
    games = []
    for g in _get_results():
        iso = _euro_to_iso(g.get("date"))
        if not iso:
            continue
        played = g.get("played") == "true"
        time_ = g.get("time") or "00:00"
        stage = stages.euroleague(g.get("round"), g.get("group"), g.get("gameday"))
        games.append({
            "id": f"euroleague:{g.get('gamenumber')}",
            "league_id": "euroleague",
            "season": code,
            "game_date": iso,
            "datetime": f"{iso}T{time_}:00",
            "status": "final" if played else "scheduled",
            "home_team_id": f"euroleague:{g.get('homecode')}",
            "away_team_id": f"euroleague:{g.get('awaycode')}",
            "home_score": g.get("homescore") if played else None,
            "away_score": g.get("awayscore") if played else None,
            "period": None,
            "clock": None,
            **stage,
        })
    # Источник отдаёт матчи в произвольном порядке — сортируем сами.
    games.sort(key=lambda x: x["datetime"])
    return games


def fetch_games(date: str) -> list[dict]:
    """Матчи за одну дату. date — в формате ГГГГММДД (напр. '20251017')."""
    target = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return [g for g in fetch_season_games() if g["game_date"] == target]


# ===== Box score (live.euroleague.net/api/Boxscore, JSON) =====
def fetch_boxscore(gamecode: str) -> dict:
    """Box score матча Евролиги: счёт по четвертям, командные итоги,
    статистика игроков (гости первыми, сначала стартовая пятёрка)."""
    url = "https://live.euroleague.net/api/Boxscore"
    r = client.get(url, params={"gamecode": gamecode, "seasoncode": _season_code()})
    r.raise_for_status()
    data = r.json()

    stats = data.get("Stats") or []
    by_quarter = data.get("ByQuarter") or []

    home_code = away_code = None
    for g in _get_results():
        if str(g.get("gamenumber")) == str(gamecode):
            home_code, away_code = g.get("homecode"), g.get("awaycode")
            break

    teams = []
    for i, team in enumerate(stats):
        players_raw = team.get("PlayersStats") or []

        code = ""
        for p in players_raw:
            if p.get("Team"):
                code = str(p.get("Team")).strip()
                break
        if not code:
            code = str(team.get("Team") or "").strip()

        info = _team_info(code)

        q = by_quarter[i] if i < len(by_quarter) else {}
        quarters = []
        n = 1
        while q.get(f"Quarter{n}") is not None:
            quarters.append(str(q.get(f"Quarter{n}")))
            n += 1
        score = str(sum(int(x) for x in quarters)) if quarters else None

        players = []
        for p in players_raw:
            mins = p.get("Minutes")
            if not mins or mins in ("0:00", "DNP"):
                continue
            players.append({
                "name": _fix_name(p.get("Player")),
                "starter": bool(p.get("IsStarter")),
                "min": mins,
                "pts": p.get("Points"),
                "reb": p.get("TotalRebounds"),
                "ast": p.get("Assistances"),
                "stl": p.get("Steals"),
                "blk": p.get("BlocksFavour"),
                "to": p.get("Turnovers"),
                "fg": f"{_num(p.get('FieldGoalsMade2')) + _num(p.get('FieldGoalsMade3'))}-{_num(p.get('FieldGoalsAttempted2')) + _num(p.get('FieldGoalsAttempted3'))}",
                "fg3": f"{_num(p.get('FieldGoalsMade3'))}-{_num(p.get('FieldGoalsAttempted3'))}",
                "ft": f"{_num(p.get('FreeThrowsMade'))}-{_num(p.get('FreeThrowsAttempted'))}",
                "pf": p.get("FoulsCommited"),
                "plus_minus": p.get("Plusminus"),
            })

        players.sort(key=lambda pl: 0 if pl["starter"] else 1)

        tr = team.get("totr") or {}
        fg_m = _num(tr.get("FieldGoalsMade2")) + _num(tr.get("FieldGoalsMade3"))
        fg_a = _num(tr.get("FieldGoalsAttempted2")) + _num(tr.get("FieldGoalsAttempted3"))
        totals = {
            "fg": f"{fg_m}-{fg_a}", "fg_pct": _pct(fg_m, fg_a),
            "fg3": f"{_num(tr.get('FieldGoalsMade3'))}-{_num(tr.get('FieldGoalsAttempted3'))}",
            "fg3_pct": _pct(tr.get("FieldGoalsMade3"), tr.get("FieldGoalsAttempted3")),
            "ft": f"{_num(tr.get('FreeThrowsMade'))}-{_num(tr.get('FreeThrowsAttempted'))}",
            "ft_pct": _pct(tr.get("FreeThrowsMade"), tr.get("FreeThrowsAttempted")),
            "reb": tr.get("TotalRebounds"), "ast": tr.get("Assistances"),
            "stl": tr.get("Steals"), "blk": tr.get("BlocksFavour"), "to": tr.get("Turnovers"),
        }

        teams.append({
            "team_id": f"euroleague:{code}",
            "name": info.get("name"),
            "short_name": info.get("short_name") or code,
            "logo": info.get("logo"),
            "score": score,
            "home_away": "home" if code == home_code else ("away" if code == away_code else None),
            "quarters": quarters,
            "players": players,
            "totals": totals,
        })

    teams.sort(key=lambda t: 0 if t["home_away"] == "away" else 1)
    return {"game_id": f"euroleague:{gamecode}", "teams": teams}


# ===== Составы =====
# Берём настоящую заявку клуба: /v2/.../clubs/{code}/people.
# Раньше здесь была выжимка из статистики за сезон — из-за неё в составах
# висели ушедшие игроки, а новичков не было вовсе (они ещё не сыграли).
_people_cache: dict = {}
_photo_cache = None


def _photos_by_code() -> dict:
    """Фотографии игроков, собранные по коду человека.

    Зачем отдельно: в заявках на новый сезон картинок нет вообще — Евролига
    снимает игроков на официальную фотосессию перед стартом, летом карточек
    ещё не существует. Зато у прошлого сезона фото есть у всех. Адрес
    картинки привязан к человеку, а не к клубу, поэтому при переходе игрока
    в другую команду ссылка остаётся рабочей.

    Собираем из двух мест: список всех людей прошлого сезона (одним запросом,
    накрывает даже тех, кто почти не играл) и статистика (на всякий случай).
    """
    global _photo_cache
    if _photo_cache is not None:
        return _photo_cache

    photos = {}

    # Все люди прошлого сезона — там картинки лежат в images у записи
    try:
        url = f"{API}/v2/competitions/{COMP}/seasons/{_season_code()}/people"
        r = client.get(url, params={"limit": 2000})
        if r.status_code == 200:
            data = r.json()
            people = data if isinstance(data, list) else (data.get("data") or [])
            total = data.get("total") if isinstance(data, dict) else None
            for item in people:
                person = item.get("person") or {}
                code = str(person.get("code") or "").strip()
                image = _person_image(item, person)
                if code and image:
                    photos[code] = image
            if total and len(people) < total:
                print(f"[составы] euroleague: список людей отдан не целиком "
                      f"({len(people)} из {total}) — часть фото может не найтись")
    except Exception as e:
        print(f"[составы] euroleague: список людей сезона не получен ({e})")

    # Статистика — как было раньше, вторым источником
    try:
        for p in _get_players():
            person = p.get("player") or {}
            code = str(person.get("code") or "").strip()
            if code and person.get("imageUrl") and code not in photos:
                photos[code] = person["imageUrl"]
    except Exception:
        pass

    _photo_cache = photos
    print(f"[составы] euroleague: собрано фотографий — {len(photos)}")
    return photos


# Названия полей с картинками у источника отличаются от места к месту,
# поэтому сначала пробуем знакомые, а потом берём любое значение, похожее
# на ссылку. Так фото найдётся, даже если поле называется по-новому.
_IMAGE_KEYS = ("headshot", "profile", "photo", "portrait", "verticalPortrait",
               "horizontalPortrait", "large", "medium", "small", "url", "imageUrl")


def _person_image(item: dict, person: dict) -> str | None:
    sources = [person.get("images") or {}, item.get("images") or {}]

    for source in sources:
        for key in _IMAGE_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value

    # знакомых полей не нашлось — берём первую попавшуюся ссылку
    for source in sources:
        for value in source.values():
            if isinstance(value, str) and value.startswith("http"):
                return value

    # иногда картинка лежит прямо у записи, без вложенного объекта
    for holder in (person, item):
        for key in ("imageUrl", "image", "photoUrl"):
            value = holder.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return None


def _cm(value):
    """Рост/вес приходят числом; ноль означает «не указано»."""
    try:
        number = int(float(value))
        return str(number) if number > 0 else None
    except Exception:
        return None


def _people(season_code: str, team_code: str) -> list:
    """Заявка клуба на сезон. Пустой список, если её ещё нет: клубы
    дозаявляются вразнобой, и у части из них адрес отвечает 404."""
    cache_key = f"{season_code}:{team_code}"
    if cache_key in _people_cache:
        return _people_cache[cache_key]

    url = f"{API}/v2/competitions/{COMP}/seasons/{season_code}/clubs/{team_code}/people"
    try:
        r = client.get(url)
        if r.status_code != 200:
            _people_cache[cache_key] = []
        else:
            data = r.json()
            _people_cache[cache_key] = data if isinstance(data, list) else (data.get("data") or [])
    except Exception:
        _people_cache[cache_key] = []
    return _people_cache[cache_key]


def fetch_roster(team_code: str) -> list[dict]:
    """Заявка клуба Евролиги: игроки с номером, амплуа, ростом и датой рождения.

    В ответе кроме игроков идут тренеры и персонал — их отсекаем по отсутствию
    игрового номера. Если у клуба есть действующие игроки (active), берём
    только их; у доигранного сезона таким образом остаётся полный состав.

    Сезон заявки может быть новее сезона матчей. Если у конкретного клуба
    новой заявки ещё нет, берём прошлую — лучше прошлогодний состав,
    чем пустой экран.
    """
    raw = _people(_roster_season_code(), team_code)
    if not raw and _roster_season_code() != _season_code():
        raw = _people(_season_code(), team_code)

    with_number = []
    for item in raw:
        dorsal = str(item.get("dorsal") or item.get("dorsalRaw") or "").strip()
        if not dorsal or dorsal == "0":
            continue                      # тренеры и персонал без номера
        with_number.append((item, dorsal))

    active = [pair for pair in with_number if pair[0].get("active")]
    chosen = active or with_number

    photos = _photos_by_code()
    players = []
    for item, dorsal in chosen:
        person = item.get("person") or {}
        person_code = str(person.get("code") or "").strip()
        birth = person.get("birthDate")
        players.append({
            "id": f"euroleague:{person_code}",
            "team_id": f"euroleague:{team_code}",
            "name": _fix_name(person.get("name")),
            "position": item.get("positionName") or item.get("position"),
            "number": dorsal,
            "height": _cm(person.get("height")),
            "weight": _cm(person.get("weight")),
            "birth_date": birth[:10] if birth else None,
            "photo_url": _person_image(item, person) or photos.get(person_code),
        })

    without_photo = sum(1 for p in players if not p["photo_url"])
    if without_photo:
        print(f"[составы] euroleague/{team_code}: игроков {len(players)}, "
              f"без фото {without_photo}")
    return players


# ===== Статистика игрока за сезон =====
_players_cache = None


def _get_players() -> list:
    """Все игроки лиги со статистикой за сезон (кешируем)."""
    global _players_cache
    if _players_cache is None:
        url = f"{API}/v3/competitions/{COMP}/statistics/players/traditional"
        params = {
            "SeasonMode": "Single",
            "SeasonCode": _season_code(),
            "statisticMode": "PerGame",
            "limit": 400,
        }
        r = client.get(url, params=params)
        r.raise_for_status()
        _players_cache = (r.json() or {}).get("players") or []
    return _players_cache


def fetch_player_stats(player_code: str) -> dict | None:
    """Статистика игрока Евролиги за сезон."""
    for p in _get_players():
        person = p.get("player") or {}
        code = str(person.get("code") or "").strip()
        if code != str(player_code).strip():
            continue

        two_m, two_a = _num(p.get("twoPointersMade")), _num(p.get("twoPointersAttempted"))
        three_m, three_a = _num(p.get("threePointersMade")), _num(p.get("threePointersAttempted"))
        return {
            "player_id": f"euroleague:{code}",
            "games_played": _i(p.get("gamesPlayed")),
            "minutes": _f1(p.get("minutesPlayed")),
            "pts": _f1(p.get("pointsScored")),
            "reb": _f1(p.get("totalRebounds")),
            "ast": _f1(p.get("assists")),
            "stl": _f1(p.get("steals")),
            "blk": _f1(p.get("blocks")),
            "tov": _f1(p.get("turnovers")),
            "pf": _f1(p.get("foulsCommited")),
            "fg_pct": _pct(two_m + three_m, two_a + three_a),
            "fg3_pct": _strip_pct(p.get("threePointersPercentage")),
            "ft_pct": _strip_pct(p.get("freeThrowsPercentage")),
        }
    return None


def clear_cache():
    """Сбрасывает кеши адаптера (чтобы автообновление взяло свежие данные)."""
    global _standings_cache, _teams_by_code, _results_cache
    global _players_cache, _people_cache, _photo_cache, _clubs_cache
    _standings_cache = None
    _teams_by_code = None
    _results_cache = None
    _players_cache = None
    _people_cache = {}
    _photo_cache = None
    _clubs_cache = {}