# explore_feeds.py
# Скрипт-разведчик по новостным лентам: проверяет кандидатов и показывает,
# какие реально работают и что отдают. Ничего в проекте не меняет.
#
# Запуск из корня проекта:  python explore_feeds.py
#
# По итогам оставляем в app/news.py -> FEEDS только рабочие ленты.

import io
import sys

import feedparser
import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Тот же клиент, что и в app/news.py: с браузерным User-Agent.
# Со служебным заголовком feedparser многие ленты отдают пустую заглушку.
client = httpx.Client(
    headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    },
    timeout=30,
    follow_redirects=True,
    trust_env=False,
)

# Помечено: [в работе] — уже стоит в app/news.py, остальное — кандидаты на добавление.
CANDIDATES = {
    "NBA (нужен английский)": [
        ("ESPN NBA [в работе]", "https://www.espn.com/espn/rss/nba/news"),
        ("NBA.com", "https://www.nba.com/rss/nba_rss.xml"),
        ("HoopsHype", "https://hoopshype.com/feed/"),
        ("CBS Sports NBA", "https://www.cbssports.com/rss/headlines/nba/"),
        ("Yahoo Sports NBA", "https://sports.yahoo.com/nba/rss.xml"),
    ],
    "Евролига (нужен английский)": [
        ("Eurohoops [в работе]", "https://www.eurohoops.net/en/feed/"),
        ("EuroLeague офиц. (rss)", "https://www.euroleaguebasketball.net/euroleague/rss/"),
        ("EuroLeague офиц. (feed)", "https://www.euroleaguebasketball.net/en/euroleague/feed/"),
        ("BasketNews", "https://basketnews.com/rss.xml"),
    ],
    "Единая лига ВТБ (нужен русский)": [
        # У «Чемпионата» есть отдельные ленты по турнирам — ссылка на них
        # стоит внизу страницы новостей турнира. Общий вид:
        #   /rss/news/basketball/<турнир>/  (vtbleague, nba, euroleague)
        ("Чемпионат — Единая лига [в работе]",
         "https://www.championat.com/rss/news/basketball/vtbleague/"),
        ("Чемпионат — весь баскетбол", "https://www.championat.com/rss/news/basketball/"),
        ("Спортс — все новости [в работе]", "https://www.sports.ru/rss/all_news.xml"),
        ("Спортс — все материалы", "https://www.sports.ru/rss/main.xml"),
        ("Спортбокс", "https://news.sportbox.ru/rss"),
        ("Матч ТВ", "https://matchtv.ru/rss"),
        ("Р-Спорт", "https://rsport.ria.ru/export/rss2/archive/index.xml"),
    ],
}


def probe(name: str, url: str) -> None:
    print(f"\n  {name}")
    print(f"  {url}")
    try:
        response = client.get(url)
        status = response.status_code
        parsed = feedparser.parse(response.content)
    except Exception as e:
        print(f"     ОШИБКА: {e}")
        return

    entries = parsed.entries or []

    if status >= 400:
        print(f"     HTTP {status} — не работает")
        return
    if parsed.get("bozo") and not entries:
        print(f"     не разобралось: {parsed.get('bozo_exception')}")
        return
    if not entries:
        print(f"     лента пустая (HTTP {status})")
        return

    print(f"     РАБОТАЕТ: HTTP {status}, новостей {len(entries)}")
    print(f"     язык:      {parsed.feed.get('language', '(не указан)')}")

    first = entries[0]
    print(f"     заголовок: {first.get('title', '')[:90]}")
    print(f"     дата:      {first.get('published', '(нет поля published)')}")
    print(f"     ссылка:    {first.get('link', '')[:90]}")

    summary = first.get("summary") or first.get("description") or ""
    print(f"     аннотация: {'есть, ' + str(len(summary)) + ' символов' if summary else 'НЕТ'}")

    has_image = bool(first.get("media_content") or first.get("media_thumbnail"))
    if not has_image:
        has_image = any(str(l.get("type", "")).startswith("image/")
                        for l in (first.get("links") or []))
    print(f"     картинка:  {'есть' if has_image else 'нет'}")


if __name__ == "__main__":
    for league, feeds in CANDIDATES.items():
        print("\n" + "=" * 70)
        print(league)
        print("=" * 70)
        for name, url in feeds:
            probe(name, url)

    print("\n\nГотово. Рабочие ленты впиши в app/news.py -> FEEDS, остальные убери.")