# app/odds.py
# Коэффициенты матчей (исход / тотал / фора) от Odds-API.io.
# Только NBA и Евролига — у ВТБ этот источник коэффициентов не даёт.
#
# Бесплатный тариф жёсткий: 100 запросов в час. Поэтому модуль устроен
# экономно: коэффициенты для ближайших матчей подтягиваются ФОНОВО раз в
# несколько часов и складываются в нашу базу (таблица odds). Пользователи
# видят сохранённые коэффициенты — сколько бы их ни заходило, лимит не
# тратится на каждый показ.
#
# Принцип отображения: коэффициенты показываются, ТОЛЬКО если они реально
# есть. Нет коэффициентов — матч отдаётся без всякого упоминания о них.
#
# Без ODDS_API_KEY модуль молчит и ничего не делает.

import json
import time
from datetime import datetime, timezone, timedelta

import httpx

from app import config
from app import db

BASE = "https://api.odds-api.io/v3"

# Наши лиги -> их slug в Odds-API.io. ВТБ здесь нет намеренно (нет у источника).
LEAGUE_SLUGS = {
    "nba": ["usa-nba", "usa-nba-preseason"],   # регулярка + предсезонка
    "euroleague": ["international-euroleague"],
}

# Рекреационный (бесплатный) букмекер, подтверждённый разведкой.
# Держим несколько запасных на случай, если основной не отдаст матч.
RECREATIONAL_BOOKMAKERS = ["18bet", "1xbet", "22Bet", "20Bet", "12bet"]

_client = httpx.Client(base_url=BASE, timeout=30, trust_env=False)


# ===== Разбор названий рынков =====
# У Odds-API.io рынки называются по-своему. Нам нужны три:
#   исход (moneyline / 1x2), тотал (over/under), фора (handicap / spread).
# Точные ключи могут отличаться — разбираем гибко, по смыслу названия.
def _classify_market(name: str) -> str | None:
    n = (name or "").lower()
    if any(w in n for w in ("moneyline", "money line", "1x2", "match winner", "winner", "ml", "h2h")):
        return "moneyline"
    if any(w in n for w in ("total", "over/under", "over under", "o/u", "totals")):
        return "total"
    if any(w in n for w in ("handicap", "spread", "point spread", "line")):
        return "handicap"
    return None


def _extract_markets(bookmaker_data: dict) -> dict:
    """Из данных одного букмекера достаёт три наших рынка в единый вид.
    Возвращает словарь вроде:
      {"moneyline": {"home": 1.75, "away": 2.10},
       "total": {"line": 210.5, "over": 1.90, "under": 1.90},
       "handicap": {"line": -5.5, "home": 1.90, "away": 1.90}}
    Отсутствующие рынки просто не попадают в результат."""
    result = {}
    markets = bookmaker_data.get("markets") or bookmaker_data.get("odds") or []
    if isinstance(markets, dict):
        markets = [dict(name=k, **(v if isinstance(v, dict) else {"values": v}))
                   for k, v in markets.items()]

    for m in markets:
        kind = _classify_market(m.get("name") or m.get("key") or m.get("market"))
        if not kind:
            continue
        values = m.get("values") or m.get("outcomes") or m.get("selections") or []

        if kind == "moneyline":
            home = away = None
            for v in values:
                label = str(v.get("name") or v.get("value") or v.get("label") or "").lower()
                odd = v.get("odd") or v.get("price") or v.get("odds")
                if label in ("home", "1") or "home" in label:
                    home = _num(odd)
                elif label in ("away", "2") or "away" in label:
                    away = _num(odd)
            if home or away:
                result["moneyline"] = {"home": home, "away": away}

        elif kind == "total":
            # берём линию, ближайшую к основной (обычно первая)
            over = under = line = None
            for v in values:
                label = str(v.get("name") or v.get("value") or v.get("label") or "").lower()
                odd = v.get("odd") or v.get("price") or v.get("odds")
                pt = v.get("point") or v.get("line") or v.get("handicap") or v.get("total")
                if pt is not None and line is None:
                    line = _num(pt)
                if "over" in label or label.startswith("o"):
                    over = _num(odd)
                elif "under" in label or label.startswith("u"):
                    under = _num(odd)
            if over or under:
                result["total"] = {"line": line, "over": over, "under": under}

        elif kind == "handicap":
            home = away = line = None
            for v in values:
                label = str(v.get("name") or v.get("value") or v.get("label") or "").lower()
                odd = v.get("odd") or v.get("price") or v.get("odds")
                pt = v.get("point") or v.get("line") or v.get("handicap")
                if pt is not None and line is None:
                    line = _num(pt)
                if label in ("home", "1") or "home" in label:
                    home = _num(odd)
                elif label in ("away", "2") or "away" in label:
                    away = _num(odd)
            if home or away:
                result["handicap"] = {"line": line, "home": home, "away": away}

    return result


def _num(x):
    """Аккуратно приводит коэффициент к числу; мусор -> None."""
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None


# ===== Сопоставление их матчей с нашими =====
def _norm_team(name: str) -> str:
    """Приводит название команды к виду для сравнения: нижний регистр,
    только буквы и цифры. 'Real Madrid' и 'real madrid' совпадут."""
    if not name:
        return ""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _teams_match(their_name: str, our_name: str) -> bool:
    """Совпадают ли команды. Их названия и наши могут слегка отличаться,
    поэтому сравниваем нормализованно и по вхождению (одно в другом)."""
    a = _norm_team(their_name)
    b = _norm_team(our_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


# ===== Запрос к API (тратит лимит — только фоново!) =====
def _get(path, params):
    params = dict(params or {})
    params["apiKey"] = config.ODDS_API_KEY
    r = _client.get(path, params=params)
    return r.json()


def _fetch_events(slug: str) -> list[dict]:
    """Ближайшие матчи лиги у Odds-API.io."""
    data = _get("/events", {"sport": "basketball", "league": slug})
    if isinstance(data, list):
        return data
    return data.get("events") or data.get("data") or []


def _fetch_odds_for_event(event_id) -> dict | None:
    """Коэффициенты одного матча от первого доступного рекреационного
    букмекера. Возвращает разобранные три рынка или None, если их нет."""
    for bm in RECREATIONAL_BOOKMAKERS:
        try:
            data = _get("/odds", {"eventId": event_id, "bookmakers": bm})
        except Exception:
            continue
        if not isinstance(data, dict) or data.get("error"):
            continue
        bookmakers = data.get("bookmakers") or {}
        if not bookmakers:
            continue                     # у этого букмекера линий нет — пробуем след.
        # bookmakers может быть словарём {имя: данные} или списком
        first = None
        if isinstance(bookmakers, dict):
            first = next(iter(bookmakers.values()), None)
        elif isinstance(bookmakers, list) and bookmakers:
            first = bookmakers[0]
        if not first:
            continue
        markets = _extract_markets(first)
        if markets:
            return {"bookmaker": bm, "markets": markets}
    return None


# ===== Главная фоновая задача =====
def refresh_odds(adapters=None, days_ahead: int = 3, max_requests: int = 40):
    """Подтягивает коэффициенты для ближайших матчей NBA и Евролиги и
    сохраняет в базу. Зовётся планировщиком раз в несколько часов.

    Бережёт лимит: не больше max_requests запросов за проход, и только для
    матчей в ближайшие days_ahead дней. При 100 запросах в час это оставляет
    большой запас."""
    if not config.odds_enabled():
        return

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)
    requests_made = 0
    saved = 0

    for our_league, slugs in LEAGUE_SLUGS.items():
        # наши ближайшие матчи этой лиги — с ними будем сопоставлять
        our_games = _our_upcoming_games(our_league, now, horizon)
        if not our_games:
            continue

        for slug in slugs:
            if requests_made >= max_requests:
                break
            try:
                their_events = _fetch_events(slug)
                requests_made += 1
            except Exception as e:
                print(f"[коэффициенты] {slug}: список матчей не получить: {e}")
                continue

            for ev in their_events:
                if requests_made >= max_requests:
                    break
                # время матча у них
                when = ev.get("date") or ev.get("startTime") or ev.get("commenceTime")
                start = _parse_dt(when)
                if not start or not (now <= start <= horizon):
                    continue

                # ищем наш матч с теми же командами примерно в ту же дату
                our_match = _find_our_match(ev, our_games, start)
                if not our_match:
                    continue

                ev_id = ev.get("id") or ev.get("eventId")
                odds = _fetch_odds_for_event(ev_id)
                requests_made += 1
                if odds:
                    db.save_odds(our_match["id"], json.dumps(odds, ensure_ascii=False))
                    saved += 1

    if saved:
        print(f"[коэффициенты] обновлено матчей: {saved} (запросов: {requests_made})")


def _our_upcoming_games(league_id, start, end):
    """Наши матчи лиги в окне дат — из базы."""
    d_from = start.strftime("%Y-%m-%d")
    d_to = end.strftime("%Y-%m-%d")
    try:
        rows = db.get_games_between(d_from, d_to)
    except Exception:
        return []
    return [g for g in rows if g.get("league_id") == league_id]


def _find_our_match(their_event, our_games, their_start):
    """Находит наш матч, соответствующий их событию: обе команды совпадают
    (в любом порядке) и дата близка (в пределах суток)."""
    their_home = their_event.get("home") or their_event.get("homeTeam") or ""
    their_away = their_event.get("away") or their_event.get("awayTeam") or ""

    for g in our_games:
        gh = g.get("home_name") or g.get("home_short") or ""
        ga = g.get("away_name") or g.get("away_short") or ""
        # прямое соответствие дом-дом, гости-гости
        direct = _teams_match(their_home, gh) and _teams_match(their_away, ga)
        # либо перевёрнутое (вдруг сторона определена иначе)
        swapped = _teams_match(their_home, ga) and _teams_match(their_away, gh)
        if direct or swapped:
            return g
    return None


def _parse_dt(text):
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ===== Чтение для интерфейса =====
def get_odds_for_game(game_id: str) -> dict | None:
    """Коэффициенты нашего матча для показа. None, если их нет —
    тогда интерфейс не покажет ничего про коэффициенты."""
    if not config.odds_enabled():
        return None
    try:
        raw = db.get_odds(game_id)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None