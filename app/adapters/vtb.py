# app/adapters/vtb.py
# Адаптер Единой лиги ВТБ. Данные — из API InfoBasket (org.infobasket.su)
# через httpx с trust_env=False. Умеет: команды, таблицу, матчи (за дату
# и за весь сезон), боксскор, составы, статистику игрока за сезон.

import httpx

from app import stages
from app import season as season_mod

client = httpx.Client(
    headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)",
    },
    timeout=30,
    trust_env=False,
)

API = "https://org.infobasket.su/Widget"
# Номера сезона берём из season.py — там единый «источник правды», чтобы не
# дублировать и обновлять в одном месте при новом сезоне.
COMP_ID = season_mod.VTB_COMP_ID       # чемпионат (таблица, команды, игроки)
SEASON_ID = season_mod.VTB_SEASON_ID   # контейнер календаря (матчи)

POS_MAP = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}


# ===== маленькие помощники =====
def _z(v):
    return v if v is not None else 0


def _pct(made, att):
    made, att = _z(made), _z(att)
    return str(round(made / att * 100)) if att else None


def _comma(s):
    """'8,6' -> '8.6'."""
    if s is None or s == "":
        return None
    return str(s).replace(",", ".")


def _logo(team_id) -> str:
    return f"{API}/GetTeamLogo/{team_id}?compId={COMP_ID}"


# ===== Команды и таблица =====
def _standings_data() -> list:
    r = client.get(f"{API}/CompTeamResults/{COMP_ID}", params={"format": "json"})
    r.raise_for_status()
    return r.json()


def fetch_teams() -> list[dict]:
    """Список команд ВТБ (берём из ответа таблицы)."""
    teams = []
    for t in _standings_data():
        cn = t.get("CompTeamName") or {}
        tid = t.get("TeamID")
        teams.append({
            "id": f"vtb:{tid}",
            "league_id": "vtb",
            "name": cn.get("CompTeamNameRu"),
            "short_name": cn.get("CompTeamShortNameRu"),
            "city": cn.get("CompTeamRegionNameRu"),
            "logo_url": _logo(tid),
        })
    return teams


# Известные сезоны ВТБ для выбора (номера вручную; при добавлении нового
# сезона прошлый съезжает сюда). code = COMP_ID сезона.
KNOWN_SEASONS = [
    {"code": str(COMP_ID), "label": season_mod.VTB_LABEL},   # текущий
    {"code": "50720", "label": "2025/26"},                   # прошлый
]

_standings_by_comp: dict = {}


def list_seasons() -> list[dict]:
    """Сезоны ВТБ для выбора в таблице. Убираем дубли по коду (если текущий
    совпал с одним из прошлых)."""
    seen, result = set(), []
    for s in KNOWN_SEASONS:
        if s["code"] in seen:
            continue
        seen.add(s["code"])
        result.append(s)
    return result


def fetch_standings_for(season_code: str) -> list[dict]:
    """Таблица ВТБ за КОНКРЕТНЫЙ сезон (по его COMP_ID). С названиями и
    логотипами команд — для прошлых сезонов их нет в базе. Кешируется."""
    if season_code in _standings_by_comp:
        return _standings_by_comp[season_code]

    rows = []
    try:
        r = client.get(f"{API}/CompTeamResults/{season_code}", params={"format": "json"})
        r.raise_for_status()
        for t in r.json():
            tid = t.get("TeamID")
            cn = t.get("CompTeamName") or {}
            st = t.get("Standings") or {}
            vp = st.get("VictoryPercent")
            win_pct = round(vp / 100, 3) if isinstance(vp, (int, float)) else None
            rows.append({
                "team_id": f"vtb:{tid}",
                "league_id": "vtb",
                "conference": None,
                "rank": t.get("Place"),
                "team_name": cn.get("CompTeamNameRu"),
                "team_short": cn.get("CompTeamShortNameRu"),
                "team_logo": f"{API}/GetTeamLogo/{tid}?compId={season_code}",
                "wins": t.get("Won"),
                "losses": t.get("Lost"),
                "win_pct": win_pct,
                "games_back": None,
                "streak": None,
            })
    except Exception as e:
        print(f"[vtb] таблица сезона {season_code} не получена: {e}")

    _standings_by_comp[season_code] = rows
    return rows


def fetch_standings() -> list[dict]:
    """Турнирная таблица ВТБ (единая, без конференций)."""
    standings = []
    for t in _standings_data():
        tid = t.get("TeamID")
        st = t.get("Standings") or {}
        vp = st.get("VictoryPercent")
        win_pct = round(vp / 100, 3) if isinstance(vp, (int, float)) else None
        standings.append({
            "team_id": f"vtb:{tid}",
            "league_id": "vtb",
            "conference": None,
            "rank": t.get("Place"),
            "wins": t.get("Won"),
            "losses": t.get("Lost"),
            "win_pct": win_pct,
            "games_back": None,
            "streak": None,
        })
    return standings


# ===== Матчи (Calendar по «контейнеру» сезона) =====
_calendar_cache = None


def _get_calendar() -> list:
    global _calendar_cache
    if _calendar_cache is None:
        r = client.get(f"{API}/Calendar/{SEASON_ID}", params={"format": "json"})
        r.raise_for_status()
        _calendar_cache = r.json()
    return _calendar_cache


def _date_to_iso(d: str):
    """'12.06.2026' -> '2026-06-12'."""
    if not d or len(d) != 10:
        return None
    return f"{d[6:10]}-{d[3:5]}-{d[0:2]}"


def fetch_season_games() -> list[dict]:
    """Все матчи сезона ВТБ одним запросом (он уже закеширован).

    Стадия берётся из поля CompNameRu: 'Регулярный чемпионат',
    '1/4 финала (1)'..'(4)', '1/2 финала (1)'..'(2)', 'Финал',
    'Финал за 3 место'. Название серии уникально, поэтому оно же служит
    её идентификатором.
    """
    games = []
    for g in _get_calendar():
        iso = _date_to_iso(g.get("GameDate"))
        if not iso:
            continue
        score_a, score_b = g.get("ScoreA"), g.get("ScoreB")
        played = bool(score_a or score_b)
        time_ = g.get("GameTime") or "00:00"
        stage = stages.vtb(g.get("CompNameRu"))
        games.append({
            "id": f"vtb:{g.get('GameID')}",
            "league_id": "vtb",
            "season": str(SEASON_ID),
            "game_date": iso,
            "datetime": f"{iso}T{time_}:00",
            "status": "final" if played else "scheduled",
            "home_team_id": f"vtb:{g.get('TeamAid')}",
            "away_team_id": f"vtb:{g.get('TeamBid')}",
            "home_score": str(score_a) if played else None,
            "away_score": str(score_b) if played else None,
            "period": None,
            "clock": None,
            **stage,
        })
    # Источник отдаёт матчи в произвольном порядке — сортируем сами.
    games.sort(key=lambda x: x["datetime"])
    return games


def fetch_games(date: str) -> list[dict]:
    """Матчи ВТБ за дату. date — в формате ГГГГММДД (напр. '20260612')."""
    target = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return [g for g in fetch_season_games() if g["game_date"] == target]


# ===== Box score (GameBoxScore; счёта по четвертям у ВТБ нет) =====
def fetch_boxscore(game_id: str) -> dict:
    """Box score матча ВТБ: командные итоги и статистика игроков
    (хозяева = TeamNumber 1, стартовые сначала). Четвертей у ВТБ нет."""
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
            "team_id": f"vtb:{code}",
            "name": tn.get("CompTeamNameRu"),
            "short_name": tn.get("CompTeamShortNameRu"),
            "logo": _logo(code),
            "score": str(team.get("Score")) if team.get("Score") is not None else None,
            "home_away": "home" if team.get("TeamNumber") == 1 else "away",
            "quarters": [],
            "players": players,
            "totals": totals,
        })

    return {"game_id": f"vtb:{game_id}", "teams": teams}


# ===== Составы и статистика игрока =====
def fetch_roster(team_id: str) -> list[dict]:
    """Состав команды ВТБ (из TeamRoster)."""
    r = client.get(f"{API}/TeamRoster/{team_id}", params={"compId": COMP_ID, "format": "json"})
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
            "id": f"vtb:{pid}",
            "team_id": f"vtb:{team_id}",
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
    """'17:35' -> '17.6' (минуты с десятыми)."""
    if not s or ":" not in str(s):
        return None
    try:
        m, sec = str(s).split(":")
        return str(round(int(m) + int(sec) / 60, 1))
    except Exception:
        return None


def fetch_player_stats(person_id: str) -> dict | None:
    """Средняя статистика игрока ВТБ за сезон (из PlayerStats)."""
    r = client.get(f"{API}/PlayerStats/{person_id}", params={"compId": COMP_ID, "format": "json"})
    r.raise_for_status()
    st = r.json()
    if not isinstance(st, dict) or not st.get("GameCount"):
        return None
    return {
        "player_id": f"vtb:{person_id}",
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


def clear_cache():
    """Сбрасывает кеш адаптера (чтобы автообновление взяло свежие данные)."""
    global _calendar_cache
    _calendar_cache = None
    _standings_by_comp.clear()