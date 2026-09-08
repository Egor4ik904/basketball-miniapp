# Проверяем составы ВТБ: по новому номеру (55613) и старому (50720).
import io, sys, httpx
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
client = httpx.Client(headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"}, timeout=20, trust_env=False)
API = "https://org.infobasket.su/Widget"

# сначала получим id команд нового сезона из таблицы
r = client.get(f"{API}/CompTeamResults/55613", params={"format":"json"})
teams = r.json()
print("Команды сезона 55613 и их id:")
team_ids = []
for t in teams[:5]:
    cn = t.get("CompTeamName") or {}
    tid = t.get("TeamID")
    team_ids.append(tid)
    print(f"  id={tid}: {cn.get('CompTeamShortNameRu')}")

# берём первую команду, проверяем состав по разным номерам
test_team = team_ids[0]
print(f"\nПроверяем состав команды id={test_team}:")
for comp in [55613, 50720]:
    try:
        r = client.get(f"{API}/TeamRoster/{test_team}", params={"compId":comp,"format":"json"})
        data = r.json()
        players = data.get("Players") or []
        print(f"  compId={comp}: игроков {len(players)}")
        if players:
            for p in players[:3]:
                pi = p.get("PersonInfo") or {}
                print(f"     {pi.get('PersonFirstNameRu','')} {pi.get('PersonLastNameRu','')}")
    except Exception as e:
        print(f"  compId={comp}: ошибка {e}")

# может, составы под season_id или другим эндпоинтом?
print(f"\nПробуем другие способы для команды {test_team}:")
for url in [
    f"{API}/CompRoster/{test_team}?compId=55613&format=json",
    f"{API}/TeamPlayers/{test_team}?compId=55613&format=json",
    f"{API}/GetTeamRoster/55613/{test_team}?format=json",
]:
    try:
        r = client.get(url)
        print(f"  {url.split('Widget/')[1][:45]}: статус {r.status_code}, размер {len(r.content)}")
    except Exception as e:
        print(f"  ошибка: {e}")

print("\nПришли вывод — поймём, залиты ли составы нового сезона.")