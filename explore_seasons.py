# explore_our_season.py
# Проверяем, какой сезон выбирает НАША логика (app/season.py) прямо сейчас.
# Это покажет, видит ли приложение новый сезон Евролиги E2026 или застряло
# на старом E2025 — от этого зависит, почему команды старые.
#
# Запуск из корня проекта:  python explore_our_season.py

import io
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# импортируем нашу же логику
from app import season

print("=" * 72)
print("Что выбирает НАША логика определения сезона")
print("=" * 72)

# Евролига
try:
    season.clear_cache()          # сбрасываем кеш, чтобы посчитать заново
    el = season.euroleague()
    print("\nЕВРОЛИГА:")
    print(f"  сезон матчей (code):     {el.get('code')}")
    print(f"  подпись (label):         {el.get('label')}")
    print(f"  доигран (finished):      {el.get('finished')}")
    print(f"  сезон составов (roster): {el.get('roster_code')}")
    print(f"  тур для таблицы:         {el.get('standings_round')}")
    if el.get('code') == 'E2026':
        print("  -> ✅ приложение ВИДИТ новый сезон E2026")
    else:
        print(f"  -> ⚠️ приложение всё ещё на {el.get('code')}, а не E2026")
except Exception as e:
    print(f"  ошибка: {e}")

# NBA
try:
    nba = season.nba()
    print("\nNBA:")
    print(f"  {nba}")
except Exception as e:
    print(f"  NBA ошибка: {e}")

# ВТБ
try:
    vtb = season.vtb()
    print("\nВТБ:")
    print(f"  {vtb}")
except Exception as e:
    print(f"  ВТБ ошибка: {e}")

print("\n\nПришли вывод — по нему пойму, видит ли приложение новые сезоны")
print("и почему команды могут быть старыми.")