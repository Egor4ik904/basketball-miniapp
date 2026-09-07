# explore_history.py
# Разведка: доступны ли ТАБЛИЦЫ ПРОШЛЫХ СЕЗОНОВ по каждой лиге и в каком виде.
# От этого зависит, как сделать выбор сезона в таблицах.

import io, sys, json
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(headers={"User-Agent":"Mozilla/5.0 (compatible; BC/1.0)",
                               "Accept":"application/json"},
                      timeout=25, trust_env=False)

def head(t):
    print("\n"+"="*72); print(t); print("="*72)

# ========== NBA — таблицы прошлых сезонов через ESPN ==========
head("NBA — таблицы прошлых сезонов (ESPN)")
STAND = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
for year in [2027, 2026, 2025, 2024, 2023]:
    try:
        r = client.get(STAND, params={"season": year, "level": "3"})
        if r.status_code != 200:
            print(f"  сезон {year}: статус {r.status_code}")
            continue
        data = r.json()
        # считаем команды в таблице
        cnt = 0
        for conf in data.get("children", []):
            for grp in (conf.get("children") or [conf]):
                st = grp.get("standings") or {}
                cnt += len(st.get("entries") or [])
        # если нет children, пробуем прямой standings
        if cnt == 0:
            st = data.get("standings") or {}
            cnt = len(st.get("entries") or [])
        print(f"  сезон {year}: команд в таблице {cnt}")
    except Exception as e:
        print(f"  сезон {year}: ошибка {e}")

# ========== Евролига — таблицы прошлых сезонов ==========
head("Евролига — таблицы прошлых сезонов (EuroLeague API)")
EL = "https://api-live.euroleague.net"
for code in ["E2026","E2025","E2024","E2023","E2022"]:
    try:
        r = client.get(f"{EL}/v1/standings", params={"seasonCode": code, "gameNumber": 34})
        ok = r.status_code == 200 and (b"<team" in r.content or b"standing" in r.content.lower())
        size = len(r.content)
        print(f"  {code}: статус {r.status_code}, размер {size}, похоже на таблицу: {ok}")
    except Exception as e:
        print(f"  {code}: ошибка {e}")

# ========== ВТБ — таблицы прошлых сезонов (нужны номера!) ==========
head("ВТБ — таблицы прошлых сезонов (InfoBasket)")
print("У ВТБ таблица берётся по COMP_ID. Текущий 50720. Проверим, отдают ли")
print("прошлые сезоны данные — нужно знать их номера. Пробуем известные:\n")
API = "https://org.infobasket.su/Widget"
# 50720 - текущий (2025/26). Прошлые сезоны — номера НЕизвестны, пробуем угадать
for comp in [50720, 50733]:  # 50720 текущий, 50733 попадался в разведке
    try:
        r = client.get(f"{API}/CompTeamResults/{comp}", params={"format":"json"})
        if r.status_code == 200 and r.content:
            data = r.json()
            if isinstance(data, list) and data:
                # даты не тут, но команды есть
                names = [(t.get("CompTeamName") or {}).get("CompTeamShortNameRu") for t in data[:3]]
                print(f"  comp={comp}: команд {len(data)}, примеры: {names}")
    except Exception as e:
        print(f"  comp={comp}: ошибка {e}")
print("\n  ВЫВОД по ВТБ: номера прошлых сезонов надо искать отдельно (как искали")
print("  текущий). Автоматически список сезонов ВТБ не отдаётся.")

print("\n\nПришли вывод — поймём, у каких лиг история достаётся легко.")