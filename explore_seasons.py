# Смотрим CompNameRu и GameNumber у матчей кубка — понять, как размечать стадии.
import io, sys, httpx
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
client = httpx.Client(headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"}, timeout=20, trust_env=False)

r = client.get("https://org.infobasket.su/Widget/Calendar/52553", params={"format":"json"})
games = r.json()
print(f"матчей: {len(games)}\n")
# группируем по CompNameRu
from collections import Counter
comps = Counter()
examples = {}
for g in games:
    cn = g.get("CompNameRu") or "(пусто)"
    comps[cn] += 1
    if cn not in examples:
        examples[cn] = f"{g.get('GameNumber')}: {g.get('ShortTeamNameAru')} {g.get('ScoreA')}:{g.get('ScoreB')} {g.get('ShortTeamNameBru')}"

print("Стадии (CompNameRu) и число матчей:")
for cn, cnt in comps.most_common():
    print(f"  '{cn}': {cnt} матчей | пример: {examples[cn]}")