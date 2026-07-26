# tools/explore_sources.py
# Скрипт-разведчик (этап 1 ТЗ): выясняет, где в ответах источников лежит
# стадия турнира (регулярка / плей-офф) и данные для сетки.
#
# Запуск из корня проекта:  python explore_sources.py
# Ничего не меняет в проекте: только читает источники, печатает выжимку
# и складывает сырые ответы в docs/sources_raw/ — чтобы можно было
# посмотреть глазами и приложить к docs/sources.md.

import io
import json
import sys
from collections import Counter
from pathlib import Path

import httpx
import xmltodict

# чтобы русские буквы не ломались в консоли Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RAW_DIR = Path("docs/sources_raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

client = httpx.Client(
    headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)",
    },
    timeout=40,
    trust_env=False,
)

# ==== ID сезонов (те же, что в адаптерах) ====
EL_SEASON = "E2025"
VTB_SEASON_ID = 50714   # «контейнер» сезона: регулярка + плей-офф
VTB_COMP_ID = 50720     # регулярный чемпионат

# Даты плей-офф NBA 2026 — подбери, если не угадал (апрель–июнь 2026).
NBA_PLAYOFF_RANGE = "20260415-20260625"


def head(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def save(name, content):
    path = RAW_DIR / name
    mode, data = ("wb", content) if isinstance(content, bytes) else ("w", content)
    with open(path, mode, encoding=None if mode == "wb" else "utf-8") as f:
        f.write(data)
    print(f"   [сырой ответ сохранён: {path}]")


def show_counter(label, values):
    """Печатает, какие значения встречаются у поля и сколько раз."""
    counter = Counter(str(v) for v in values)
    print(f"   {label}:")
    for value, count in counter.most_common(30):
        print(f"      {value!r} — {count} матч(ей)")


# ============================================================
# 1. ЕВРОЛИГА
# ============================================================
def explore_euroleague():
    head("1. ЕВРОЛИГА — api-live.euroleague.net/v1/results")
    try:
        r = client.get(
            "https://api-live.euroleague.net/v1/results",
            params={"seasonCode": EL_SEASON},
        )
        r.raise_for_status()
        save("euroleague_results.xml", r.content)

        games = xmltodict.parse(r.content)["results"]["game"]
        if isinstance(games, dict):
            games = [games]
        print(f"   Всего матчей за сезон: {len(games)}")

        print("\n   Поля одного матча (полный список):")
        for key in games[0].keys():
            print(f"      {key}")

        for field in ("round", "gameday", "group", "phase"):
            if field in games[0]:
                print()
                show_counter(f"Значения поля '{field}'", [g.get(field) for g in games])

        print("\n   ПЕРВЫЙ матч сезона целиком:")
        print(json.dumps(games[0], ensure_ascii=False, indent=6))
        print("\n   ПОСЛЕДНИЙ матч сезона целиком (это должен быть финал):")
        print(json.dumps(games[-1], ensure_ascii=False, indent=6))

    except Exception as e:
        print(f"   ОШИБКА: {e}")


# ============================================================
# 2. ЕДИНАЯ ЛИГА ВТБ
# ============================================================
def explore_vtb():
    head("2. ВТБ — org.infobasket.su/Widget/Calendar")
    try:
        r = client.get(
            f"https://org.infobasket.su/Widget/Calendar/{VTB_SEASON_ID}",
            params={"format": "json"},
        )
        r.raise_for_status()
        save("vtb_calendar.json", r.text)

        games = r.json()
        print(f"   Всего матчей в «контейнере» сезона: {len(games)}")

        print("\n   Поля одного матча (полный список):")
        for key in games[0].keys():
            print(f"      {key}")

        # Всё, что похоже на признак стадии/турнира
        interesting = [
            k for k in games[0]
            if any(word in k.lower() for word in ("comp", "stage", "tour", "round", "type", "status"))
        ]
        for field in interesting:
            print()
            show_counter(f"Значения поля '{field}'", [g.get(field) for g in games])

        print("\n   ПЕРВЫЙ матч целиком:")
        print(json.dumps(games[0], ensure_ascii=False, indent=6))
        print("\n   ПОСЛЕДНИЙ матч целиком (должен быть финал плей-офф):")
        print(json.dumps(games[-1], ensure_ascii=False, indent=6))

    except Exception as e:
        print(f"   ОШИБКА: {e}")

    # Список турниров внутри сезона — вдруг есть готовое дерево стадий
    head("2б. ВТБ — есть ли справочник турниров сезона?")
    for path in (f"/Widget/Comp/{VTB_SEASON_ID}", f"/Widget/CompStages/{VTB_COMP_ID}"):
        url = f"https://org.infobasket.su{path}"
        try:
            r = client.get(url, params={"format": "json"})
            print(f"   {path} -> HTTP {r.status_code}")
            if r.status_code == 200 and r.text.strip():
                save(path.strip("/").replace("/", "_") + ".json", r.text)
                print("      " + r.text[:600])
        except Exception as e:
            print(f"   {path} -> ошибка: {e}")


# ============================================================
# 3. NBA
# ============================================================
def explore_nba():
    head("3. NBA — ESPN scoreboard, диапазон дат плей-офф")
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    try:
        r = client.get(url, params={"dates": NBA_PLAYOFF_RANGE, "limit": 1000})
        r.raise_for_status()
        data = r.json()
        events = data.get("events", [])
        print(f"   Диапазон {NBA_PLAYOFF_RANGE}: получено матчей — {len(events)}")

        if not events:
            print("   Пусто. Значит диапазон дат не поддержан или даты не те.")
            print("   Поменяй NBA_PLAYOFF_RANGE на одну дату (напр. '20260610') и перезапусти.")
            return

        save("nba_playoffs.json", json.dumps(data, ensure_ascii=False)[:2_000_000])

        # season.type: 2 = регулярка, 3 = плей-офф
        show_counter(
            "Значения season.type",
            [(e.get("season") or {}).get("type") for e in events],
        )
        show_counter(
            "Значения season.slug",
            [(e.get("season") or {}).get("slug") for e in events],
        )

        last = events[-1]
        comp = (last.get("competitions") or [{}])[0]

        print("\n   Последний матч диапазона — 'notes' (название стадии):")
        print(json.dumps(comp.get("notes"), ensure_ascii=False, indent=6))

        print("\n   Последний матч диапазона — 'series' (счёт серии для сетки):")
        print(json.dumps(comp.get("series"), ensure_ascii=False, indent=6))

        print("\n   Ключи объекта competitions[0] (что вообще доступно):")
        for key in comp.keys():
            print(f"      {key}")

    except Exception as e:
        print(f"   ОШИБКА: {e}")


if __name__ == "__main__":
    explore_euroleague()
    explore_vtb()
    explore_nba()
    print("\n\nГотово. Сырые ответы — в папке docs/sources_raw/")