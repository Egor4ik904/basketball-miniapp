# explore_odds_io.py  (версия 6 — вытаскиваем коэффициенты из 8 LIVE матчей)
# Live баскетбол ЕСТЬ. Проходим по всем live-матчам и по каждому перебираем
# букмекеров настойчиво, пока не найдём непустые коэффициенты. Показываем
# реальный формат рынков: исход / тотал / фора.

import io, os, sys, httpx, json
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

KEY = os.getenv("ODDS_API_KEY", "").strip()
BASE = "https://api.odds-api.io/v3"
client = httpx.Client(base_url=BASE, timeout=30, trust_env=False)

def head(t):
    print("\n" + "=" * 72); print(t); print("=" * 72)

# список букмекеров
all_bms = []
try:
    r = client.get("/bookmakers")
    data = r.json()
    bms = data if isinstance(data, list) else (data.get("bookmakers") or [])
    all_bms = [(b.get("slug") or b.get("name")) if isinstance(b, dict) else b for b in bms]
    print(f"букмекеров всего: {len(all_bms)}")
except Exception as e:
    print("ошибка букмекеров:", e)

# получаем live баскетбол
head("Live баскетбольные матчи")
bb_live = []
try:
    r = client.get("/events/live", params={"apiKey": KEY})
    data = r.json()
    live = data if isinstance(data, list) else (data.get("events") or data.get("data") or [])
    for e in live:
        sp = e.get("sport")
        sp_slug = sp.get("slug","") if isinstance(sp, dict) else str(sp)
        if "basket" in sp_slug.lower():
            bb_live.append(e)
    print(f"   баскетбольных live: {len(bb_live)}")
    for e in bb_live:
        print(f"     {e.get('home')} — {e.get('away')} ({(e.get('league') or {}).get('name')}) id={e.get('id')}")
except Exception as e:
    print("   ошибка:", e)

# по каждому матчу — настойчивый перебор ВСЕХ букмекеров до непустых коэфов
head("Ищем непустые коэффициенты (перебор всех букмекеров по каждому матчу)")
found = None
for e in bb_live:
    eid = e.get("id") or e.get("eventId")
    print(f"\n   матч {e.get('home')} — {e.get('away')}:")
    hit_bms = []
    for bm in all_bms:
        try:
            r = client.get("/odds", params={"eventId": eid, "bookmakers": bm, "apiKey": KEY})
            resp = r.json()
            if isinstance(resp, dict) and not resp.get("error"):
                bmk = resp.get("bookmakers") or {}
                if bmk:
                    hit_bms.append(bm)
                    if not found:
                        found = resp
                    if len(hit_bms) >= 1:
                        break   # хватит одного рабочего на этот матч
        except Exception:
            continue
    print(f"      букмекеров с коэффициентами: {hit_bms if hit_bms else 'нет (все платные/пусто)'}")
    if found:
        break

# формат
head("ФОРМАТ коэффициентов — исход / тотал / фора")
if found:
    print(json.dumps(found, ensure_ascii=False, indent=2)[:3500])
else:
    print("   Ни у одного live-матча не нашлось коэффициентов от рекреационных")
    print("   букмекеров (возможно, эти матчи покрывают только платные книги).")
    print("   Формат рынков возьму из документации при написании модуля.")

print("\n\nПришли вывод целиком.")