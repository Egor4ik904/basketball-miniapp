# app/adapters/vtbcup.py
# Адаптер внутрисезонного турнира Единой лиги ВТБ — Winline Basket Cup.
# Источник тот же, что у чемпионата ВТБ (InfoBasket), только другие номера.
# Отличие от чемпионата: команды разбиты на ДВЕ ГРУППЫ (A и B), у каждой
# своя мини-таблица. Календарь общий для всего турнира.
#
# ПРИМЕЧАНИЕ: номера заданы вручную; в новом розыгрыше их нужно обновить
# (как и у чемпионата ВТБ). Найти можно на сайте wbc.vtb-league.com — номер
# виден в адресе виджета таблицы (?compId=...), а номера групп — рядом.

import httpx

from app import stages

client = httpx.Client(
    headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)",
    },
    timeout=30,
    trust_env=False,
)

API = "https://org.infobasket.su/Widget"

# --- Номера турнира (обновлять при новом розыгрыше) ---
CUP_COMP_ID = 52553          # весь турнир (общий список команд, календарь-контейнер)
CUP_SEASON_ID = 52553        # контейнер календаря турнира
GROUP_A_ID = 52554           # Группа A (таблица)
GROUP_B_ID = 52555           # Группа B (таблица)
GROUP_A_LABEL = "Группа A"
GROUP_B_LABEL = "Группа B"

# Розыгрыши кубка для выбора сезона. У каждого свои номера: comp (турнир и
# календарь) и номера двух групп. При новом розыгрыше добавить его сюда
# первым (номера с сайта wbc.vtb-league.com).
CUP_EDITIONS = [
    {"code": "52553", "label": "2025/26",
     "group_a": "52554", "group_b": "52555"},
]

POS_MAP = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}


# ===== помощники (те же, что у ВТБ) =====
def _z(v):
    return v if v is not None else 0


def _pct(made, att):
    made, att = _z(made), _z(att)
    return str(round(made / att * 100)) if att else None


def _comma(s):
    if s is None or s == "":
        return None
    return str(s).replace(",", ".")


def _logo(team_id) -> str:
    return f"{API}/GetTeamLogo/{team_id}?compId={CUP_COMP_ID}"


# ===== Команды и таблицы (по группам) =====
def _comp_team_results(comp_id) -> list:
    r = client.get(f"{API}/CompTeamResults/{comp_id}", params={"format": "json"})
    r.raise_for_status()
    return r.json()


def fetch_teams() -> list[dict]:
    """Все команды турнира — из общей таблицы (8 команд)."""
    teams = []
    for t in _comp_team_results(CUP_COMP_ID):
        cn = t.get("CompTeamName") or {}
        tid = t.get("TeamID")
        teams.append({
            "id": f"vtbcup:{tid}",
            "league_id": "vtbcup",
            "name": cn.get("CompTeamNameRu"),
            "short_name": cn.get("CompTeamShortNameRu"),
            "city": cn.get("CompTeamRegionNameRu"),
            "logo_url": _logo(tid),
        })
    return teams


def _standings_for_group(comp_id, group_label) -> list[dict]:
    """Таблица одной группы. conference = метка группы (A/B) — фронт по ней
    разложит команды в две отдельные таблицы."""
    rows = []
    for t in _comp_team_results(comp_id):
        tid = t.get("TeamID")
        cn = t.get("CompTeamName") or {}
        st = t.get("Standings") or {}
        vp = st.get("VictoryPercent")
        win_pct = round(vp / 100, 3) if isinstance(vp, (int, float)) else None
        rows.append({
            "team_id": f"vtbcup:{tid}",
            "league_id": "vtbcup",
            "conference": group_label,      # <- группа как «конференция»
            "rank": t.get("Place"),
            "team_name": cn.get("CompTeamNameRu"),
            "team_short": cn.get("CompTeamShortNameRu"),
            "team_logo": f"{API}/GetTeamLogo/{tid}?compId={comp_id}",
            "wins": t.get("Won"),
            "losses": t.get("Lost"),
            "win_pct": win_pct,
            "games_back": None,
            "streak": None,
        })
    return rows


def fetch_standings() -> list[dict]:
    """Таблицы обеих групп вместе. Каждая строка помечена своей группой
    (в поле conference), фронт разложит их в две таблицы A и B."""
    standings = []
    standings += _standings_for_group(GROUP_A_ID, GROUP_A_LABEL)
    standings += _standings_for_group(GROUP_B_ID, GROUP_B_LABEL)
    return standings


# ===== Матчи (общий календарь турнира) =====
_calendar_cache = None


def _get_calendar() -> list:
    global _calendar_cache
    if _calendar_cache is None:
        r = client.get(f"{API}/Calendar/{CUP_SEASON_ID}", params={"format": "json"})
        r.raise_for_status()
        _calendar_cache = r.json()
    return _calendar_cache


def _date_to_iso(d: str):
    if not d or len(d) != 10:
        return None
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}"


def fetch_season_games() -> list[dict]:
    """Все матчи турнира. Стадия берётся из CompNameRu (групповой этап,
    полуфиналы, финал и т.п.) — как и у чемпионата ВТБ."""
    games = []
    for g in _get_calendar():
        iso = _date_to_iso(g.get("GameDate"))
        if not iso:
            continue
        score_a, score_b = g.get("ScoreA"), g.get("ScoreB")
        played = bool(score_a or score_b)
        time_ = g.get("GameTime") or "00:00"
        stage = stages.vtbcup(g.get("CompNameRu"), g.get("GameID"))
        games.append({
            "id": f"vtbcup:{g.get('GameID')}",
            "league_id": "vtbcup",
            "season": str(CUP_SEASON_ID),
            "game_date": iso,
            "datetime": f"{iso}T{time_}:00",
            "status": "final" if played else "scheduled",
            "home_team_id": f"vtbcup:{g.get('TeamAid')}",
            "away_team_id": f"vtbcup:{g.get('TeamBid')}",
            "home_score": str(score_a) if played else None,
            "away_score": str(score_b) if played else None,
            "period": None,
            "clock": None,
            **stage,
        })
    games.sort(key=lambda x: x["datetime"])
    return games


def fetch_games(date: str) -> list[dict]:
    target = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return [g for g in fetch_season_games() if g["game_date"] == target]


# ===== Box score (тот же формат, что у ВТБ) =====
def fetch_boxscore(game_id: str) -> dict:
    r = client.get(f"{API}/GameBoxScore/{game_id}", params={"format": "json"})
    r.raise_for_status()
    data = r.json()

    teams = []
    for team in (data.get("Teams") or []):
        tn = team.get("TeamName") or {}
        code = team.get("TeamID")

        players = []
        for p in (team.get("Players") or []):
            pt = p.get("PlayedTime")
            if not pt or pt in ("0:00", "00:00"):
                continue
            players.append({
                "name": f"{(p.get('FirstNameRu') or '').strip()} {(p.get('LastNameRu') or '').strip()}".strip(),
                "starter": bool(p.get("IsStart")),
                "min": pt,
                "pts": _z(p.get("Points")),
                "reb": _z(p.get("Rebound")),
                "ast": _z(p.get("Assist")),
                "stl": _z(p.get("Steal")),
                "blk": _z(p.get("Blocks")),
                "to": _z(p.get("Turnover")),
                "fg": f"{_z(p.get('Goal2')) + _z(p.get('Goal3'))}-{_z(p.get('Shot2')) + _z(p.get('Shot3'))}",
                "fg3": f"{_z(p.get('Goal3'))}-{_z(p.get('Shot3'))}",
                "ft": f"{_z(p.get('Goal1'))}-{_z(p.get('Shot1'))}",
                "pf": _z(p.get("Foul")),
                "plus_minus": p.get("PlusMinus"),
            })
        players.sort(key=lambda pl: 0 if pl["starter"] else 1)

        fg_m = _z(team.get("Goal2")) + _z(team.get("Goal3"))
        fg_a = _z(team.get("Shot2")) + _z(team.get("Shot3"))
        totals = {
            "fg": f"{fg_m}-{fg_a}", "fg_pct": _pct(fg_m, fg_a),
            "fg3": f"{_z(team.get('Goal3'))}-{_z(team.get('Shot3'))}",
            "fg3_pct": _pct(team.get("Goal3"), team.get("Shot3")),
            "ft": f"{_z(team.get('Goal1'))}-{_z(team.get('Shot1'))}",
            "ft_pct": _pct(team.get("Goal1"), team.get("Shot1")),
            "reb": team.get("Rebound"), "ast": team.get("Assist"),
            "stl": team.get("Steal"), "blk": team.get("Blocks"), "to": team.get("Turnover"),
        }

        teams.append({
            "team_id": f"vtbcup:{code}",
            "name": tn.get("CompTeamNameRu"),
            "short_name": tn.get("CompTeamShortNameRu"),
            "logo": _logo(code),
            "score": str(team.get("Score")) if team.get("Score") is not None else None,
            "home_away": "home" if team.get("TeamNumber") == 1 else "away",
            "quarters": [],
            "players": players,
            "totals": totals,
        })

    return {"game_id": f"vtbcup:{game_id}", "teams": teams}


# ===== Составы и статистика игрока (по номеру турнира) =====
def fetch_roster(team_id: str) -> list[dict]:
    r = client.get(f"{API}/TeamRoster/{team_id}", params={"compId": CUP_COMP_ID, "format": "json"})
    r.raise_for_status()
    data = r.json()

    players = []
    for p in (data.get("Players") or []):
        pi = p.get("PersonInfo") or {}
        pid = pi.get("PersonID")
        first = (pi.get("PersonFirstNameRu") or "").strip()
        last = (pi.get("PersonLastNameRu") or "").strip()
        name = (f"{first} {last}".strip()) or pi.get("PersonFullNameRu")
        players.append({
            "id": f"vtbcup:{pid}",
            "team_id": f"vtbcup:{team_id}",
            "name": name,
            "position": POS_MAP.get(p.get("PosID")),
            "number": p.get("DisplayNumber") or (str(p.get("PlayerNumber")) if p.get("PlayerNumber") is not None else None),
            "height": str(p.get("Height")) if p.get("Height") else None,
            "weight": str(p.get("Weight")) if p.get("Weight") else None,
            "birth_date": pi.get("PersonBirth"),
            "photo_url": p.get("PhotoUrl"),
        })
    return players


def _mmss_to_minutes(s):
    if not s or ":" not in str(s):
        return None
    try:
        m, sec = str(s).split(":")
        return str(round(int(m) + int(sec) / 60, 1))
    except Exception:
        return None


def fetch_player_stats(person_id: str) -> dict | None:
    r = client.get(f"{API}/PlayerStats/{person_id}", params={"compId": CUP_COMP_ID, "format": "json"})
    r.raise_for_status()
    st = r.json()
    if not isinstance(st, dict) or not st.get("GameCount"):
        return None
    return {
        "player_id": f"vtbcup:{person_id}",
        "games_played": str(st.get("GameCount")),
        "minutes": _mmss_to_minutes(st.get("AvgPlayedTime")),
        "pts": _comma(st.get("AvgPoints")),
        "reb": _comma(st.get("AvgRebound")),
        "ast": _comma(st.get("AvgAssist")),
        "stl": _comma(st.get("AvgSteal")),
        "blk": _comma(st.get("AvgBlocks")),
        "tov": _comma(st.get("AvgTurnover")),
        "pf": _comma(st.get("AvgFoul")),
        "fg_pct": _comma(st.get("Shot23Percent")),
        "fg3_pct": _comma(st.get("Shot3Percent")),
        "ft_pct": _comma(st.get("Shot1Percent")),
    }


def list_seasons() -> list[dict]:
    """Розыгрыши кубка для выбора сезона (новые сверху)."""
    return [{"code": e["code"], "label": e["label"]} for e in CUP_EDITIONS]


def _edition(code):
    """Находит розыгрыш по коду; по умолчанию — первый (текущий)."""
    for e in CUP_EDITIONS:
        if e["code"] == code:
            return e
    return CUP_EDITIONS[0] if CUP_EDITIONS else None


def fetch_standings_for(season_code: str) -> list[dict]:
    """Таблицы обеих групп за КОНКРЕТНЫЙ розыгрыш кубка. Каждая строка помечена
    группой (conference) — фронт разложит по группам."""
    e = _edition(season_code)
    if not e:
        return []
    rows = []
    rows += _standings_for_group(int(e["group_a"]), GROUP_A_LABEL)
    rows += _standings_for_group(int(e["group_b"]), GROUP_B_LABEL)
    return rows


def fetch_playoff_for(season_code: str) -> list[dict]:
    """Матчи плей-офф (финал четырёх) за КОНКРЕТНЫЙ розыгрыш — для сетки."""
    e = _edition(season_code)
    if not e:
        return []
    comp = e["code"]
    # имена/логотипы команд розыгрыша
    names = {}
    try:
        for t in client.get(f"{API}/CompTeamResults/{comp}",
                            params={"format": "json"}).json():
            tid = t.get("TeamID")
            cn = t.get("CompTeamName") or {}
            names[f"vtbcup:{tid}"] = {
                "name": cn.get("CompTeamNameRu"),
                "short": cn.get("CompTeamShortNameRu"),
                "logo": f"{API}/GetTeamLogo/{tid}?compId={comp}",
                "seed": t.get("Place"),
            }
    except Exception as ex:
        print(f"[vtbcup] команды розыгрыша {comp} не получены: {ex}")

    rows = []
    try:
        cal = client.get(f"{API}/Calendar/{comp}", params={"format": "json"}).json() or []
    except Exception as ex:
        print(f"[vtbcup] календарь розыгрыша {comp} не получен: {ex}")
        cal = []

    for g in cal:
        stage = stages.vtbcup(g.get("CompNameRu"), g.get("GameID"))
        if stage.get("stage") != "playoff":
            continue
        iso = _date_to_iso(g.get("GameDate"))
        score_a, score_b = g.get("ScoreA"), g.get("ScoreB")
        played = bool(score_a or score_b)
        home_id = f"vtbcup:{g.get('TeamAid')}"
        away_id = f"vtbcup:{g.get('TeamBid')}"
        h = names.get(home_id, {})
        a = names.get(away_id, {})
        rows.append({
            "id": f"vtbcup:{g.get('GameID')}",
            "game_date": iso,
            "datetime": f"{iso}T{g.get('GameTime') or '00:00'}:00",
            "status": "final" if played else "scheduled",
            "home_score": str(score_a) if played else None,
            "away_score": str(score_b) if played else None,
            "stage": stage.get("stage"), "stage_label": stage.get("stage_label"),
            "series_key": stage.get("series_key"), "series_round": stage.get("series_round"),
            "home_team_id": home_id,
            "home_name": h.get("name"), "home_short": h.get("short"),
            "home_logo": h.get("logo"), "home_seed": h.get("seed"), "home_conf": None,
            "away_team_id": away_id,
            "away_name": a.get("name"), "away_short": a.get("short"),
            "away_logo": a.get("logo"), "away_seed": a.get("seed"), "away_conf": None,
        })
    rows.sort(key=lambda r: (r["series_round"] or 0, r["series_key"] or "", r["datetime"]))
    return rows


def clear_cache():
    global _calendar_cache
    _calendar_cache = None