# explore_match_times.py
# Разведка перед уведомлениями. Уведомления («за час до матча», «за 15 минут»)
# держатся на точном времени НАЧАЛА будущего матча. Проверяем по каждой лиге:
#   - есть ли вообще запланированные (будущие) матчи;
#   - приходит ли у них реальное время старта, а не заглушка 00:00;
#   - в каком виде это время и часовой пояс.
#
# Сейчас межсезонье, поэтому будущих матчей может не быть совсем — тогда
# смотрим на последние сыгранные, чтобы понять, как выглядит поле времени,
# и заодно пробуем предсезонные игры NBA (они появляются раньше).
#
# Запуск из корня проекта:  python explore_match_times.py

import io
import sys
from datetime import datetime, timezone

import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(
    headers={"Accept": "application/json",
             "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)"},
    timeout=40, follow_redirects=True, trust_env=False,
)

NOW = datetime.now(timezone.utc)


def head(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ============================================================
# NBA (ESPN scoreboard)
# ============================================================
def nba_times():
    head("NBA — время матчей (ESPN)")
    print("У ESPN каждое событие несёт date в ISO с зоной (Z = UTC).")
    print("Проверяем ближайшие дни: предсезонка NBA обычно стартует в начале")
    print("октября, что-то уже может быть в расписании.\n")

    base = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

    # пробегаем несколько будущих дат — вдруг расписание уже опубликовано
    found_future = 0
    for day_offset in (0, 7, 30, 60, 75, 80, 85, 90):
        target = NOW.timestamp() + day_offset * 86400
        d = datetime.fromtimestamp(target, tz=timezone.utc).strftime("%Y%m%d")
        try:
            r = client.get(base, params={"dates": d})
            events = (r.json() or {}).get("events", [])
        except Exception as e:
            print(f"  {d}: ошибка {e}")
            continue
        if not events:
            continue
        ev = events[0]
        status = (((ev.get("status") or {}).get("type") or {}).get("state"))
        date_iso = ev.get("date")
        print(f"  +{day_offset:>2} дн ({d}): матчей {len(events)}, "
              f"статус первого «{status}», время: {date_iso}")
        # разберём, будущее ли это время и как далеко
        try:
            dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
            delta_h = (dt - NOW).total_seconds() / 3600
            when = "будущее" if delta_h > 0 else "прошлое"
            print(f"          -> {when}, до старта ~{delta_h:.1f} ч, "
                  f"есть точное время: {'да' if dt.strftime('%H:%M') != '00:00' else 'НЕТ (00:00)'}")
            if delta_h > 0:
                found_future += 1
        except Exception as e:
            print(f"          -> время не разобрать: {e}")

    if not found_future:
        print("\n  Будущих матчей не нашлось. Смотрим последний сыгранный —")
        print("  как выглядит поле времени у него:")
        for day_offset in (-1, -2, -5, -30, -120):
            target = NOW.timestamp() + day_offset * 86400
            d = datetime.fromtimestamp(target, tz=timezone.utc).strftime("%Y%m%d")
            r = client.get(base, params={"dates": d})
            events = (r.json() or {}).get("events", [])
            if events:
                ev = events[0]
                print(f"     {d}: {ev.get('date')} — "
                      f"«{(((ev.get('status') or {}).get('type') or {}).get('state'))}»")
                break


# ============================================================
# ЕВРОЛИГА (v1/results, XML)
# ============================================================
def euroleague_times():
    head("Евролига — время матчей (v1/results)")
    print("Расписание отдаётся в XML. У матча есть date, time, played.")
    print("Проверяем, есть ли будущие игры и стоит ли у них реальное время.\n")

    import xmltodict
    # текущий и следующий сезон
    for season in ("E2025", "E2026"):
        try:
            r = client.get("https://api-live.euroleague.net/v1/results",
                           params={"seasonCode": season})
            if r.status_code != 200 or not r.content.strip():
                print(f"  {season}: пусто (HTTP {r.status_code})")
                continue
            data = xmltodict.parse(r.content)
            games = (data.get("results") or {}).get("game") or []
            if isinstance(games, dict):
                games = [games]
        except Exception as e:
            print(f"  {season}: ошибка {e}")
            continue

        total = len(games)
        played = [g for g in games if g.get("played") == "true"]
        not_played = [g for g in games if g.get("played") != "true"]
        print(f"  {season}: всего матчей {total}, сыграно {len(played)}, "
              f"не сыграно {len(not_played)}")

        sample = (not_played or played)[:3]
        for g in sample:
            date = g.get("date")
            time_ = g.get("time")
            played_flag = g.get("played")
            print(f"     date={date!r} time={time_!r} played={played_flag} "
                  f"({g.get('hometeam')} — {g.get('awayteam')})")
        if not_played:
            print(f"     -> есть будущие матчи с временем: "
                  f"{'да' if any(g.get('time') for g in not_played) else 'НЕТ'}")


# ============================================================
# ВТБ (InfoBasket Calendar)
# ============================================================
def vtb_times():
    head("ВТБ — время матчей (InfoBasket Calendar)")
    print("Календарь сезона: у матча есть дата и, важно, время начала.")
    print("Проверяем поля времени у ближайших игр.\n")

    # известные номера сезона 2025/26
    for comp_id, label in ((50714, "сезон 2025/26 (весь)"), (50720, "регулярка 2025/26")):
        try:
            r = client.get(f"https://org.infobasket.su/Widget/Calendar/{comp_id}",
                           params={"format": "json"})
            games = r.json() if r.status_code == 200 else []
        except Exception as e:
            print(f"  {comp_id}: ошибка {e}")
            continue

        if not isinstance(games, list) or not games:
            print(f"  {comp_id} ({label}): матчей нет")
            continue

        # какие поля вообще есть у матча — печатаем ключи первого
        first = games[0]
        time_keys = [k for k in first.keys()
                     if any(w in k.lower() for w in ("date", "time", "start", "utc"))]
        print(f"  {comp_id} ({label}): матчей {len(games)}")
        print(f"     поля времени: {time_keys}")

        # показываем значения этих полей у первых матчей
        for g in games[:2]:
            vals = {k: g.get(k) for k in time_keys}
            score = f"{g.get('ScoreA')}:{g.get('ScoreB')}"
            print(f"     {vals}  счёт={score}")


if __name__ == "__main__":
    nba_times()
    euroleague_times()
    vtb_times()
    print("\n\nГотово. Пришли вывод целиком — по нему пойму, у каких лиг есть")
    print("надёжное время будущих матчей, и как строить рассылку уведомлений.")