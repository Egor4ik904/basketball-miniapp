# app/notifier.py
# Рассылка уведомлений о матчах избранного.
#
# Как работает: планировщик раз в минуту зовёт check_and_send(). Она смотрит
# ближайшие матчи всех лиг, сопоставляет с подписками пользователей и шлёт
# тем, у кого подходит момент. Каждое уведомление уходит один раз — за этим
# следит журнал sent_notifications (иначе «за час до» слалось бы 60 раз).
#
# Моменты (moment) для команд — по выбору пользователя:
#   hour  — за ~60 минут       min30 — за ~30 минут
#   min10 — за ~10 минут        start — матч начался
#   final — матч завершён (с итоговым счётом)
# Для лиг и игроков момент один — league15 / player15 (за 15 минут).
# Плюс для игрока после матча — статистика (этим займётся этап 4).

import asyncio
from datetime import datetime, timezone, timedelta

from app import userdata
from app import config

# Насколько заранее шлём и с каким допуском. Проверка идёт раз в минуту,
# поэтому ловим момент в окне [минуты-1 .. минуты]: за час = когда до старта
# осталось от 59 до 60 минут. Так уведомление уходит ровно раз и вовремя.
WINDOW_MIN = 1

# минуты до старта для каждого «предупреждающего» момента
LEAD_MINUTES = {
    "hour": 60,
    "min30": 30,
    "min10": 10,
    "league15": 15,
    "player15": 15,
}


def _minutes_until(dt_start, now):
    """Сколько минут до начала матча (может быть отрицательным, если прошёл)."""
    return (dt_start - now).total_seconds() / 60.0


def _in_window(minutes_left, lead):
    """Настал ли момент «за lead минут». Ловим в окне шириной WINDOW_MIN,
    чтобы при проверке раз в минуту сработать ровно один раз."""
    return lead - WINDOW_MIN < minutes_left <= lead


def _fmt_time_msk(dt_start):
    """Время матча по Москве для текста уведомления."""
    # dt_start в UTC; Москва = UTC+3
    from datetime import timedelta
    msk = dt_start.astimezone(timezone(timedelta(hours=3)))
    return msk.strftime("%H:%M")


def _teams_line(game):
    """«Лейкерс — Селтикс» из полей матча."""
    home = game.get("home_short") or game.get("home_name") or "?"
    away = game.get("away_short") or game.get("away_name") or "?"
    return f"{home} — {away}"


# ===== Тексты уведомлений =====
def _text_lead(game, minutes):
    when = {60: "Через час", 30: "Через 30 минут", 15: "Через 15 минут",
            10: "Через 10 минут"}.get(minutes, f"Через {minutes} минут")
    return f"🏀 {when}: {_teams_line(game)}\nНачало в {_fmt_time_msk(game['_start'])} мск"


def _text_start(game):
    return f"🔴 Начался матч: {_teams_line(game)}"


def _text_final(game):
    home = game.get("home_short") or game.get("home_name") or "?"
    away = game.get("away_short") or game.get("away_name") or "?"
    hs = game.get("home_score")
    as_ = game.get("away_score")
    return f"🏁 Матч завершён:\n{home} {hs} : {as_} {away}"


# ===== Разбор времени матча =====
def _parse_start(game):
    """Извлекает время начала матча как datetime в UTC. Возвращает None,
    если времени нет или оно не разбирается (тогда предупреждать не о чем)."""
    raw = game.get("datetime") or game.get("game_date")
    if not raw:
        return None
    try:
        # формат '2026-10-10T23:00:00' (может быть с зоной или без)
        text = str(raw)
        if "T" not in text:
            return None                # только дата, без времени — не годится
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # у наших матчей время в UTC по смыслу — помечаем как UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ===== Основной проход =====
def collect_upcoming_games(adapters=None):
    """Ближайшие матчи всех лиг для рассылки — берём ИЗ БАЗЫ, а не тянем весь
    сезон через адаптеры. Рассылке интересны только матчи в окне «недавно
    закончился .. начнётся в ближайшие сутки», поэтому запрашиваем лишь
    соседние игровые дни. Это не держит тысячи матчей в памяти и не ходит
    в сеть каждую минуту. Возвращает словарь game_id -> данные матча."""
    from app.db import get_games_between

    now = datetime.now(timezone.utc)
    # игровой день у нас может отличаться от календарного на несколько часов,
    # поэтому берём вчера/сегодня/завтра — с запасом на разницу поясов
    days = [(now + timedelta(days=d)).strftime("%Y-%m-%d") for d in (-1, 0, 1)]

    try:
        rows = get_games_between(min(days), max(days))
    except Exception as e:
        print(f"[уведомления] матчи из базы не получить: {e}")
        return {}

    games = {}
    for g in rows:
        start = _parse_start(g)
        if not start:
            continue
        minutes_left = _minutes_until(start, now)
        if -240 <= minutes_left <= 24 * 60:
            g = dict(g)
            g["_start"] = start
            g["_minutes_left"] = minutes_left
            games[g["id"]] = g
    return games


def _decide_moments(game, fav, now):
    """Какие уведомления пора слать этому подписчику по этому матчу.
    Возвращает список (moment, text)."""
    minutes_left = game["_minutes_left"]
    status = game.get("status")
    out = []

    if fav["kind"] == "team":
        prefs = fav.get("prefs") or {}
        # предупреждающие моменты
        for moment in ("hour", "min30", "min10"):
            if prefs.get(moment) and _in_window(minutes_left, LEAD_MINUTES[moment]):
                out.append((moment, _text_lead(game, LEAD_MINUTES[moment])))
        # старт: время начала настало (окно вокруг нуля, т.к. проверяем раз
        # в минуту) или матч уже перешёл в идущий
        started = (-2 <= minutes_left <= 1) or status in ("live", "in", "inprogress")
        if prefs.get("start") and started and status != "final":
            out.append(("start", _text_start(game)))
        # финал: матч завершён
        if prefs.get("final") and status == "final":
            out.append(("final", _text_final(game)))

    elif fav["kind"] == "league":
        # лига: за 15 минут до любого её матча
        if _in_window(minutes_left, 15):
            out.append(("league15", _text_lead(game, 15)))

    elif fav["kind"] == "player":
        # игрок: за 15 минут до матча его команды. Но чтобы знать, играет ли
        # его команда в этом матче, нужен состав — это свяжем в этапе 4.
        # Пока момент заготовлен, но без привязки игрок-команда не шлём.
        pass

    return out


async def check_and_send(adapters, bot):
    """Один проход рассылки. Зовётся планировщиком раз в пару минут.

    Порядок проверок — от дешёвого к дорогому, чтобы в спокойное время
    (межсезонье, нет матчей) выходить как можно раньше и не нагружать базу:
    сперва смотрим ближайшие матчи (лёгкий запрос к кешу матчей в нашей
    базе), и только если они есть — поднимаем подписки пользователей."""
    if not (userdata.available() and bot):
        return

    # 1) есть ли вообще матчи в ближайшие часы. Нет матчей — слать нечего,
    #    выходим, не трогая таблицы подписок.
    games = collect_upcoming_games(adapters)
    if not games:
        return

    # 2) теперь можно поднять подписки — но только раз матчи есть
    favorites = userdata.all_favorites_for_notify()
    if not favorites:
        return

    now = datetime.now(timezone.utc)
    sent_count = 0

    for fav in favorites:
        # какие матчи касаются этой подписки
        for game in games.values():
            if not _game_matches_fav(game, fav):
                continue
            for moment, text in _decide_moments(game, fav, now):
                if userdata.was_sent(fav["tg_id"], game["id"], moment):
                    continue
                try:
                    await bot.send_message(fav["tg_id"], text)
                    userdata.mark_sent(fav["tg_id"], game["id"], moment)
                    sent_count += 1
                except Exception as e:
                    # пользователь мог заблокировать бота — не роняем рассылку
                    print(f"[уведомления] не удалось отправить {fav['tg_id']}: {e}")

    if sent_count:
        print(f"[уведомления] отправлено: {sent_count}")


def _game_matches_fav(game, fav):
    """Относится ли матч к подписке."""
    kind = fav["kind"]
    if kind == "league":
        return game.get("league_id") == fav["entity_id"]
    if kind == "team":
        # подписка на команду: матч, где она дома или в гостях
        return fav["entity_id"] in (game.get("home_team_id"), game.get("away_team_id"))
    return False


def check_and_send_sync(adapters, bot):
    """Обёртка для планировщика (он синхронный, а отправка асинхронная)."""
    try:
        asyncio.run(check_and_send(adapters, bot))
    except Exception as e:
        print(f"[уведомления] проход прерван: {e}")