# app/season.py
# Определение текущего сезона для каждой лиги.
#
# Зачем: раньше сезон был зашит в код (E2025, 50720, границы дат NBA).
# Первого октября приложение бодро показывало бы прошлый сезон, пока
# кто-нибудь не полез бы править константы. Теперь спрашиваем источник.
#
# Разные лиги дают разный уровень самостоятельности:
#   Евролига — полный список сезонов с датами и победителем: определяется само;
#   NBA      — ESPN пишет год и границы сезона в каждом ответе: определяется само;
#   ВТБ      — справочника турниров нет (проверено, все адреса отвечают 404),
#              номера задаются руками, но приложение предупреждает, когда
#              сезон закончился.

from datetime import datetime

import httpx
import xmltodict

client = httpx.Client(
    headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)",
    },
    timeout=30,
    trust_env=False,
)

EL_API = "https://api-live.euroleague.net"
EL_COMP = "E"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

# ===== ВТБ: обновлять руками раз в год =====
# У InfoBasket нет справочника турниров, поэтому номера подсматриваются
# на сайте лиги. Когда сезон закончится, приложение напишет об этом в лог.
#   VTB_COMP_ID   — регулярный чемпионат (таблица, команды, составы, статистика)
#   VTB_SEASON_ID — «контейнер» сезона (календарь: регулярка + плей-офф)
VTB_COMP_ID = 50720
VTB_SEASON_ID = 50714
VTB_LABEL = "2025/26"

# Результаты держим в памяти: они не меняются посреди дня, а запросов
# на их вычисление уходит несколько.
_cache = {}


def clear_cache():
    """Сбрасывает запомненные сезоны (планировщик зовёт раз в сутки)."""
    _cache.clear()


def _parse_date(value):
    """'2026-07-01T00:00:00' -> datetime. None, если формат неожиданный."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


# ============================================================
# ЕВРОЛИГА
# ============================================================
def _el_seasons() -> list:
    """Все сезоны Евролиги, от новых к старым.
    У каждого есть code ('E2025'), alias ('2025-26'), даты и winner —
    победитель заполнен только у доигранных сезонов."""
    r = client.get(f"{EL_API}/v2/competitions/{EL_COMP}/seasons")
    r.raise_for_status()
    seasons = (r.json() or {}).get("data") or []
    return sorted(seasons, key=lambda s: s.get("year") or 0, reverse=True)


def _el_has_games(season_code: str) -> bool:
    """Опубликовано ли расписание сезона. Новый сезон заводится заранее
    (E2026 существует с 1 июля), но матчей в нём ещё нет — по этому и отличаем."""
    r = client.get(f"{EL_API}/v1/results", params={"seasonCode": season_code})
    return r.status_code == 200 and b"<game" in r.content


def _el_clubs(season_code: str) -> list:
    r = client.get(f"{EL_API}/v2/competitions/{EL_COMP}/seasons/{season_code}/clubs")
    if r.status_code != 200:
        return []
    return (r.json() or {}).get("data") or []


def _el_people(season_code: str, club_code: str) -> list:
    r = client.get(
        f"{EL_API}/v2/competitions/{EL_COMP}/seasons/{season_code}/clubs/{club_code}/people"
    )
    if r.status_code != 200:
        return []
    data = r.json()
    return data if isinstance(data, list) else (data.get("data") or [])


def _el_standings_round(season_code: str) -> int:
    """Номер тура для турнирной таблицы: последний СТАРТОВАВШИЙ тур
    регулярного чемпионата. Раньше здесь стояло зашитое 38."""
    r = client.get(f"{EL_API}/v2/competitions/{EL_COMP}/seasons/{season_code}/rounds")
    if r.status_code != 200:
        return 1

    rounds = (r.json() or {}).get("data") or []
    regular = [x for x in rounds if x.get("phaseTypeCode") == "RS" and x.get("round")]
    if not regular:
        return 1

    now = datetime.now()
    started = [x for x in regular if (_parse_date(x.get("minGameStartDate")) or now) <= now]
    return max(started or regular, key=lambda x: x["round"])["round"]


def euroleague() -> dict:
    """Сезон Евролиги, из которого берём данные.

    Отдаёт словарь:
      code             — код сезона для матчей, таблицы и статистики
      label            — как показать человеку ('2025-26')
      finished         — сезон доигран (у источника заполнен победитель)
      standings_round  — номер тура для таблицы
      roster_code      — сезон, из которого брать составы
      roster_current   — совпадает ли он с последним сезоном

    Про два разных сезона. Заявки на новый сезон публикуются раньше, чем
    расписание: клубы дозаявляются в августе, а календарь появляется позже.
    Поэтому составы берём из самого свежего сезона, где они уже есть,
    а матчи и таблицу — из последнего, где есть игры.
    """
    if "euroleague" in _cache:
        return _cache["euroleague"]

    now = datetime.now()
    seasons = _el_seasons()

    # Сезон с данными: самый новый из начавшихся, где есть матчи.
    data_season = None
    for s in seasons:
        start = _parse_date(s.get("startDate"))
        if start and start > now:
            continue                       # ещё не открыт
        if _el_has_games(s.get("code")):
            data_season = s
            break
    if data_season is None:
        data_season = seasons[0] if seasons else {"code": "E2025", "alias": "2025-26"}

    # Сезон для команд и составов — отдельный от сезона матчей.
    #
    # Так устроен сам турнир: участников объявляют весной, заявки клубы
    # собирают летом, а календарь публикуется позже. Поэтому список клубов
    # нового сезона появляется задолго до расписания, и держаться за старый
    # незачем: команды, которые в новом сезоне не играют, показывать не надо,
    # а новых — надо. Берём самый свежий сезон, где список клубов уже есть.
    #
    # Сверять составы клубов между сезонами (как я пробовал раньше) — неверно
    # по сути: они И ДОЛЖНЫ отличаться, состав участников меняется каждый год.
    roster_code = data_season.get("code")
    try:
        for s in seasons:
            start = _parse_date(s.get("startDate"))
            if start and start > now:
                continue                   # сезон ещё не открыт
            if _el_clubs(s.get("code")):
                roster_code = s.get("code")
                break
    except Exception as e:
        print(f"[сезон] Евролига: сезон составов не уточнить ({e})")

    result = {
        "code": data_season.get("code"),
        "label": data_season.get("alias") or data_season.get("name"),
        "finished": bool(data_season.get("winner")),
        "standings_round": _el_standings_round(data_season.get("code")),
        "roster_code": roster_code,
        "roster_current": roster_code == data_season.get("code"),
    }
    _cache["euroleague"] = result

    note = "" if result["roster_current"] else f", составы из {roster_code}"
    print(f"[сезон] Евролига: {result['code']} ({result['label']}), "
          f"тур {result['standings_round']}"
          + (", доигран" if result["finished"] else "") + note)
    return result


# ============================================================
# NBA
# ============================================================
def _nba_has_games(start: str, end: str) -> bool:
    """Опубликовано ли расписание сезона."""
    if not (start and end):
        return False
    try:
        r = client.get(f"{ESPN_BASE}/scoreboard", params={
            "dates": f"{start.replace('-', '')}-{end.replace('-', '')}",
            "limit": 1,
        })
        return bool((r.json() or {}).get("events"))
    except Exception:
        return False


def nba() -> dict:
    """Сезон NBA. ESPN сам пишет год и границы сезона рядом с матчами,
    поэтому даты не зашиваем — берём оттуда."""
    if "nba" in _cache:
        return _cache["nba"]

    year, start, end, label = None, None, None, None
    try:
        r = client.get(f"{ESPN_BASE}/scoreboard")
        r.raise_for_status()
        leagues = (r.json() or {}).get("leagues") or []
        season = (leagues[0] or {}).get("season") if leagues else None
        if season:
            year = season.get("year")
            label = season.get("displayName")
            start = (season.get("startDate") or "")[:10] or None
            end = (season.get("endDate") or "")[:10] or None
    except Exception as e:
        print(f"[сезон] NBA: не удалось узнать у источника ({e}), считаем по дате")

    # Запасной вариант: сезон идёт с октября по июнь, год сезона —
    # это год, в котором он ЗАКАНЧИВАЕТСЯ (сезон 2025/26 у ESPN — 2026).
    if not (year and start and end):
        now = datetime.now()
        year = now.year + 1 if now.month >= 8 else now.year
        start = f"{year - 1}-10-01"
        end = f"{year}-06-30"
        label = f"{year - 1}-{str(year)[2:]}"

    # ESPN переключается на новый сезон, как только он объявлен, — а матчей
    # в нём ещё нет. Показывать пустоту незачем: если расписание не вышло,
    # откатываемся на предыдущий сезон.
    if not _nba_has_games(start, end):
        previous = year - 1
        start = f"{previous - 1}-10-01"
        end = f"{previous}-06-30"
        label = f"{previous - 1}-{str(previous)[2:]}"
        year = previous
        print(f"[сезон] NBA: расписание нового сезона ещё не вышло, "
              f"откатываемся на {label}")

    result = {"year": year, "label": label, "start": start, "end": end}
    _cache["nba"] = result
    print(f"[сезон] NBA: {label} ({start} — {end})")
    return result


# ============================================================
# ЕДИНАЯ ЛИГА ВТБ
# ============================================================
def vtb() -> dict:
    """Сезон ВТБ. Номера турниров задаются вручную вверху файла —
    справочника у источника нет. Здесь же проверяем, не пора ли их обновить."""
    if "vtb" in _cache:
        return _cache["vtb"]

    result = {
        "comp_id": VTB_COMP_ID,
        "season_id": VTB_SEASON_ID,
        "label": VTB_LABEL,
        "finished": False,
    }

    # Признак «сезон доигран»: в календаре не осталось несыгранных матчей.
    try:
        r = client.get(f"https://org.infobasket.su/Widget/Calendar/{VTB_SEASON_ID}",
                       params={"format": "json"})
        r.raise_for_status()
        games = r.json() or []
        upcoming = [g for g in games if not (g.get("ScoreA") or g.get("ScoreB"))]
        result["finished"] = bool(games) and not upcoming

        if result["finished"]:
            print(f"[сезон] ВТБ: сезон {VTB_LABEL} доигран — все {len(games)} матчей "
                  f"сыграны. Когда объявят новый, обнови VTB_COMP_ID и "
                  f"VTB_SEASON_ID в app/season.py "
                  f"(номера видны в адресах виджетов на сайте лиги).")
        else:
            print(f"[сезон] ВТБ: {VTB_LABEL}, впереди матчей — {len(upcoming)}")
    except Exception as e:
        print(f"[сезон] ВТБ: календарь не проверить ({e})")

    _cache["vtb"] = result
    return result


def teams_season(league_id: str) -> str | None:
    """Какой сезон считать актуальным для СПИСКА КОМАНД.

    Нужен, чтобы на вкладке «Команды» были участники нового сезона, а не
    прошлогодние. При этом старые команды остаются в базе — иначе в таблице
    прошлого сезона у них пропали бы названия и логотипы.

    None означает «фильтровать не нужно»: у NBA состав лиги не меняется,
    а у ВТБ до объявления нового турнира и брать неоткуда.
    """
    try:
        if league_id == "euroleague":
            return euroleague()["roster_code"]
        if league_id == "vtb":
            return str(vtb()["comp_id"])
    except Exception:
        pass
    return None


def label_for(league_id: str) -> str:
    """Подпись сезона для главного экрана."""
    try:
        if league_id == "euroleague":
            return euroleague()["label"]
        if league_id == "nba":
            return nba()["label"]
        if league_id == "vtb":
            return vtb()["label"]
    except Exception:
        pass
    return ""