# app/scheduler.py
# Планировщик: фоновые задачи, которые по расписанию обновляют данные ВСЕХ лиг
# в базе. Список адаптеров передаётся из main.py: start_scheduler(ADAPTERS).

import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.db import (
    save_teams, save_standings, save_games, save_news,
    get_team_ids, replace_team_players,
    get_stale_player_ids, save_player_stats,
)
from app import news
from app import season as season_mod


def _clear_caches(adapters):
    """Сбрасывает кеши адаптеров — чтобы обновление взяло свежие данные."""
    for adapter in adapters.values():
        if hasattr(adapter, "clear_cache"):
            try:
                adapter.clear_cache()
            except Exception:
                pass


def refresh_today_games(adapters):
    """Счёт сегодняшних матчей — но только в дни, когда матчи реально есть.
    Если сегодня у лиги матчей нет, лигу тихо пропускаем (не дёргаем впустую)."""
    _clear_caches(adapters)   # берём свежее расписание/счёт
    today = datetime.now().strftime("%Y-%m-%d")

    for lid, adapter in adapters.items():
        if not hasattr(adapter, "fetch_games"):
            continue
        try:
            games = adapter.fetch_games(today.replace("-", ""))
            if not games:
                continue                      # сегодня матчей нет — пропускаем
            save_games(games)
            # сколько из них идёт прямо сейчас (для NBA статус приходит честно)
            live = sum(1 for g in games if g.get("status") == "live")
            print(f"[планировщик] {lid}: матчей сегодня — {len(games)}"
                  + (f", идёт сейчас — {live}" if live else ""))
        except Exception as e:
            print(f"[планировщик] {lid}: матчи не обновлены: {e}")


def refresh_season_games(adapters):
    """Матчи всего сезона: подтягивает перенесённые игры, новые туры и
    появившиеся серии плей-офф. Именно эта задача наполняет сетку."""
    _clear_caches(adapters)
    for lid, adapter in adapters.items():
        if not hasattr(adapter, "fetch_season_games"):
            continue
        try:
            n = save_games(adapter.fetch_season_games())
            print(f"[планировщик] {lid}: матчей за сезон обновлено — {n}")
        except Exception as e:
            print(f"[планировщик] {lid}: сезон не обновлён: {e}")


def refresh_news(adapters):
    """Новости всех лиг. Дубликаты отсекаются на уровне базы (ключ — ссылка
    на оригинал), поэтому ленты можно спокойно перечитывать целиком."""
    for lid in adapters:
        try:
            n = save_news(news.fetch_league(lid))
            print(f"[планировщик] {lid}: новостей обновлено — {n}")
        except Exception as e:
            print(f"[планировщик] {lid}: новости не обновлены: {e}")


def refresh_player_stats(adapters):
    """Обновляет статистику уже просмотренных игроков.

    Без этой задачи цифры замерзали навсегда: карточка игрока запрашивала
    статистику только когда её не было в базе. За сезон средние меняются
    после каждого матча, поэтому их надо перечитывать.

    Берём порциями, с паузой между запросами — источникам это привычнее,
    чем сотни обращений подряд.
    """
    for lid, adapter in adapters.items():
        if not hasattr(adapter, "fetch_player_stats"):
            continue
        updated = 0
        try:
            for player_id in get_stale_player_ids(lid):
                try:
                    stats = adapter.fetch_player_stats(player_id.split(":")[1])
                    if stats:
                        save_player_stats(stats)
                        updated += 1
                except Exception:
                    pass                      # один игрок не должен ломать всю задачу
                time.sleep(0.2)
            if updated:
                print(f"[планировщик] {lid}: статистика игроков обновлена — {updated}")
        except Exception as e:
            print(f"[планировщик] {lid}: статистика не обновлена: {e}")


def refresh_seasons(adapters):
    """Раз в сутки перечитывает, какой сезон сейчас идёт. Нужно, чтобы
    приложение переключилось на новый сезон само, без перезапуска."""
    season_mod.clear_cache()
    for lid in adapters:
        try:
            season_mod.label_for(lid)
        except Exception as e:
            print(f"[планировщик] {lid}: сезон не перечитан: {e}")


def refresh_standings(adapters):
    """Турнирные таблицы всех лиг."""
    _clear_caches(adapters)
    for lid, adapter in adapters.items():
        if not hasattr(adapter, "fetch_standings"):
            continue
        try:
            n = save_standings(adapter.fetch_standings())
            print(f"[планировщик] {lid}: таблица обновлена — {n}")
        except Exception as e:
            print(f"[планировщик] {lid}: таблица не обновлена: {e}")


def refresh_teams(adapters):
    """Команды всех лиг."""
    _clear_caches(adapters)
    for lid, adapter in adapters.items():
        if not hasattr(adapter, "fetch_teams"):
            continue
        try:
            n = save_teams(adapter.fetch_teams())
            print(f"[планировщик] {lid}: команды обновлены — {n}")
        except Exception as e:
            print(f"[планировщик] {lid}: команды не обновлены: {e}")


def refresh_rosters(adapters):
    """Составы всех команд всех лиг (с удалением ушедших игроков)."""
    _clear_caches(adapters)
    for lid, adapter in adapters.items():
        if not hasattr(adapter, "fetch_roster"):
            continue
        try:
            total = 0
            for tid in get_team_ids(lid, season_mod.teams_season(lid)):
                try:
                    players = adapter.fetch_roster(tid.split(":")[1])
                except Exception:
                    continue                      # один клуб не рушит остальные
                if players:                       # пустой состав не затираем
                    replace_team_players(tid, players)
                    total += len(players)
                time.sleep(0.3)
            print(f"[планировщик] {lid}: составы обновлены — {total} игроков")
        except Exception as e:
            print(f"[планировщик] {lid}: составы не обновлены: {e}")


def run_notifications(adapters, bot, loop):
    """Проход рассылки уведомлений. Планировщик синхронный и в отдельном
    потоке, а отправка асинхронная и должна идти в главном цикле бота —
    поэтому передаём корутину в основной event loop и ждём результат."""
    import asyncio
    from app import notifier
    try:
        future = asyncio.run_coroutine_threadsafe(
            notifier.check_and_send(adapters, bot), loop)
        future.result(timeout=50)      # не дольше интервала задачи
    except Exception as e:
        print(f"[уведомления] проход прерван: {e}")


def cleanup_notifications():
    """Раз в сутки убирает старые записи журнала уведомлений."""
    from app import userdata
    try:
        removed = userdata.cleanup_sent(days=3)
        if removed:
            print(f"[уведомления] журнал очищен: удалено {removed}")
    except Exception as e:
        print(f"[уведомления] очистка не удалась: {e}")


def start_scheduler(adapters, bot=None, loop=None):
    """Создаёт планировщик и запускает задачи обновления данных всех лиг.
    bot и loop нужны для рассылки уведомлений: планировщик работает в фоновом
    потоке, а отправка сообщений должна идти в основном цикле бота."""
    scheduler = BackgroundScheduler()

    # Счёт матчей — часто (live-режим).
    scheduler.add_job(refresh_today_games, "interval", minutes=2,
                      args=[adapters], id="games")

    # Новости — раз в полчаса.
    scheduler.add_job(refresh_news, "interval", minutes=30,
                      args=[adapters], id="news")

    # Весь сезон целиком: переносы, новые туры, серии плей-офф.
    scheduler.add_job(refresh_season_games, "interval", hours=6,
                      args=[adapters], id="season_games")

    scheduler.add_job(refresh_standings, "interval", hours=3,
                      args=[adapters], id="standings")
    scheduler.add_job(refresh_player_stats, "interval", hours=6,
                      args=[adapters], id="player_stats")
    scheduler.add_job(refresh_seasons, "interval", hours=24,
                      args=[adapters], id="seasons")
    scheduler.add_job(refresh_teams, "interval", hours=24,
                      args=[adapters], id="teams")
    scheduler.add_job(refresh_rosters, "interval", hours=24,
                      args=[adapters], id="rosters")

    # Уведомления о матчах — раз в минуту. Работают только если есть бот,
    # главный цикл и база пользователей (иначе слать некому и нечем).
    if bot is not None and loop is not None:
        scheduler.add_job(run_notifications, "interval", minutes=1,
                          args=[adapters, bot, loop], id="notifications")
        scheduler.add_job(cleanup_notifications, "interval", hours=24,
                          id="notify_cleanup")
        print("[планировщик] рассылка уведомлений включена")

    scheduler.start()
    print("[планировщик] Запущен (автообновление данных всех лиг)")
    return scheduler