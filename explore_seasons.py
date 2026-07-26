# explore_seasons2.py
# Добивка после первой разведки. Проверяем две догадки:
#
#   1) У Евролиги работает ветка v2, а не v3 (v3 отвечал 400).
#      Значит и составы, и список сезонов надо искать в v2.
#   2) У InfoBasket справочника турниров «вообще» нет, но может найтись
#      список турниров КОНКРЕТНОЙ команды — а это ровно то, что нужно:
#      по нему видно и новый сезон, и актуальную заявку.
#
# Запуск из корня проекта:  python explore_seasons2.py

import io
import json
import sys

import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

client = httpx.Client(
    headers={"Accept": "application/json",
             "User-Agent": "Mozilla/5.0 (compatible; BasketballCenter/1.0)"},
    timeout=40, follow_redirects=True, trust_env=False,
)

EL = "https://api-live.euroleague.net"
IB = "https://org.infobasket.su/Widget"
VTB_TEAM = 2994          # «Зенит»


def probe(label, url, params=None, preview=500):
    print(f"\n  {label}")
    print(f"  {url}" + (f"  {params}" if params else ""))
    try:
        r = client.get(url, params=params)
    except Exception as e:
        print(f"     ОШИБКА СЕТИ: {e}")
        return

    if r.status_code != 200:
        print(f"     HTTP {r.status_code}")
        return
    if not r.text.strip():
        print("     HTTP 200, пустой ответ")
        return

    try:
        data = r.json()
    except Exception:
        print(f"     HTTP 200, не JSON: {r.text[:preview]}")
        return

    if isinstance(data, list):
        print(f"     РАБОТАЕТ: список из {len(data)}")
        if data:
            print("     ВСЕ поля первого:", ", ".join(map(str, data[0].keys()))
                  if isinstance(data[0], dict) else type(data[0]).__name__)
            print("     первый:", json.dumps(data[0], ensure_ascii=False)[:preview])
    elif isinstance(data, dict):
        print(f"     РАБОТАЕТ: объект")
        print("     ВСЕ поля:", ", ".join(data.keys()))
        print("     содержимое:", json.dumps(data, ensure_ascii=False)[:preview])


print("=" * 72)
print("1. ЕВРОЛИГА — ветка v2: составы и сезоны")
print("=" * 72)
probe("список сезонов", f"{EL}/v2/competitions/E/seasons")
probe("сезон целиком", f"{EL}/v2/competitions/E/seasons/E2025")
probe("клубы сезона", f"{EL}/v2/competitions/E/seasons/E2025/clubs")
probe("СОСТАВ клуба", f"{EL}/v2/competitions/E/seasons/E2025/clubs/MAD/people")
probe("все люди сезона", f"{EL}/v2/competitions/E/seasons/E2025/people")
probe("туры сезона", f"{EL}/v2/competitions/E/seasons/E2025/rounds")
probe("новый сезон: клубы", f"{EL}/v2/competitions/E/seasons/E2026/clubs")

print("\n" + "=" * 72)
print("2. ВТБ — турниры конкретной команды")
print("=" * 72)
for path in ("TeamComps", "TeamCompList", "TeamSeasons", "TeamCompsList",
             "CompsByTeam", "TeamHistory"):
    probe(path, f"{IB}/{path}/{VTB_TEAM}", {"format": "json"})

print("\n\nГотово. Присылай вывод — по нему соберу определение сезона.")