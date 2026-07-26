# explore_photos_and_vtb.py
# Два дела за один запуск:
#
#   1) Смотрим, где в заявке Евролиги лежат фотографии игроков — и лежат ли
#      вообще. Нужно, чтобы понять, можно ли вытащить больше фото.
#   2) Ищем турниры Единой лиги ВТБ на новый сезон. Пока их в источнике нет,
#      обновлять лигу нечем; как появятся — впишем номера в app/season.py.
#
# Запуск из корня проекта:  python explore_photos_and_vtb.py

import io
import json
import sys
import time

import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(
    headers={"Accept": "application/json",
             "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)"},
    timeout=30, follow_redirects=True, trust_env=False,
)

EL = "https://api-live.euroleague.net"
IB = "https://org.infobasket.su/Widget"

# Номера турниров сезона 2025/26 — от них пляшем в поиске
VTB_KNOWN = (50714, 50720)
# Диапазон поиска. Если ничего не найдётся, попробуй сдвинуть верхнюю границу.
SCAN_FROM, SCAN_TO = 50700, 51400


# ============================================================
# 1. Фотографии игроков Евролиги
# ============================================================
def euroleague_photos():
    print("=" * 72)
    print("1. ЕВРОЛИГА — где лежат фотографии игроков")
    print("=" * 72)

    for season in ("E2026", "E2025"):
        print(f"\n--- сезон {season} ---")
        try:
            r = client.get(f"{EL}/v2/competitions/E/seasons/{season}/clubs/MAD/people")
            if r.status_code != 200:
                print(f"   HTTP {r.status_code}")
                continue
            data = r.json()
            people = data if isinstance(data, list) else (data.get("data") or [])
        except Exception as e:
            print(f"   ОШИБКА: {e}")
            continue

        players = [p for p in people
                   if str(p.get("dorsal") or "").strip() not in ("", "0")]
        print(f"   всего записей {len(people)}, из них с номером (игроки) {len(players)}")

        with_photo = 0
        for p in players[:6]:
            person = p.get("person") or {}
            person_images = person.get("images") or {}
            item_images = p.get("images") or {}
            has = bool(person_images) or bool(item_images)
            if has:
                with_photo += 1
            print(f"\n   #{p.get('dorsal')} {person.get('name')}")
            print(f"      person.images: {json.dumps(person_images, ensure_ascii=False)[:220]}")
            print(f"      item.images:   {json.dumps(item_images, ensure_ascii=False)[:220]}")

        print(f"\n   у первых шести картинки есть у {with_photo}")

    # Для сравнения: что отдаёт статистика (оттуда фото брались раньше)
    print("\n--- для сравнения: фото в статистике сезона ---")
    try:
        r = client.get(f"{EL}/v3/competitions/E/statistics/players/traditional",
                       params={"SeasonMode": "Single", "SeasonCode": "E2025",
                               "statisticMode": "PerGame", "limit": 3})
        players = (r.json() or {}).get("players") or []
        for p in players:
            person = p.get("player") or {}
            print(f"   {person.get('name')}: {person.get('imageUrl')}")
    except Exception as e:
        print(f"   ОШИБКА: {e}")


# ============================================================
# 2. Поиск турниров ВТБ на новый сезон
# ============================================================
def vtb_scan():
    print("\n\n" + "=" * 72)
    print("2. ВТБ — ищем турниры нового сезона")
    print("=" * 72)
    print(f"  Известные номера сезона 2025/26: {VTB_KNOWN}")
    print(f"  Перебираем {SCAN_FROM}–{SCAN_TO}. Это займёт пару минут.")
    print("  Ищем всё, что относится к Единой лиге ВТБ.\n")

    found = []
    checked = 0
    for comp_id in range(SCAN_FROM, SCAN_TO + 1):
        checked += 1
        if checked % 100 == 0:
            print(f"     ...проверено {checked}, найдено {len(found)}")
        try:
            r = client.get(f"{IB}/Calendar/{comp_id}",
                           params={"format": "json"}, timeout=10)
            if r.status_code != 200 or not r.text.strip():
                continue
            games = r.json()
            if not isinstance(games, list) or not games:
                continue

            first = games[0]
            league = str(first.get("LeagueNameRu") or "")
            if "ВТБ" not in league and "Единая" not in league:
                continue

            dates = sorted(g.get("GameDate") or "" for g in games)
            found.append({
                "id": comp_id,
                "league": league,
                "comp": first.get("CompNameRu"),
                "games": len(games),
                "from": dates[0] if dates else "?",
                "to": dates[-1] if dates else "?",
            })
            print(f"     НАЙДЕНО {comp_id}: {league} / {first.get('CompNameRu')} "
                  f"— матчей {len(games)}")
        except Exception:
            pass
        time.sleep(0.05)          # не заваливаем источник

    print(f"\n  Проверено номеров: {checked}. Найдено турниров: {len(found)}")
    if not found:
        print("  Ничего. Значит новый сезон ещё не заведён — это нормально,")
        print("  календарь обычно появляется в конце августа. Запусти позже.")
        return

    print("\n  Итог (свежие сезоны — внизу):")
    for f in sorted(found, key=lambda x: x["from"]):
        mark = "  <-- уже используем" if f["id"] in VTB_KNOWN else ""
        print(f"     {f['id']}: {f['comp']:<28} {f['from']} — {f['to']}, "
              f"матчей {f['games']}{mark}")

    print("\n  Что делать: в app/season.py вписать в VTB_SEASON_ID номер турнира,")
    print("  где матчей больше всего (это «контейнер» всего сезона), а в")
    print("  VTB_COMP_ID — номер регулярного чемпионата.")


if __name__ == "__main__":
    euroleague_photos()
    vtb_scan()
    print("\n\nГотово.")