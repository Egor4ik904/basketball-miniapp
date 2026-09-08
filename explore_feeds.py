# Через наш адаптер смотрим round/group матчей Финала четырёх Евролиги.
import io, sys
sys.path.insert(0,'.')
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.adapters import euroleague as EL

for season in ["E2024","E2023"]:
    print(f"\n=== {season}: сырые матчи с round/group ===")
    try:
        games = EL._get_results_for(season)
        print(f"  всего матчей: {len(games)}")
        seen = set()
        for g in games:
            rnd = (g.get("round") or "").strip()
            grp = (g.get("group") or "").strip()
            if rnd in ("PO","FF","PI"):
                key = (rnd, grp)
                if key not in seen:
                    seen.add(key)
                    # команды по кодам
                    h = g.get("homecode",""); a = g.get("awaycode","")
                    print(f"  round={rnd!r}, group={grp!r}  ({h}-{a}) played={g.get('played')}")
    except Exception as e:
        print(f"  ошибка: {e}")

print("\nПришли вывод — увидим точные названия групп Финала четырёх.")