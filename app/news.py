# app/news.py
# Новости лиг (раздел 7 ТЗ). Читаем RSS-ленты и приводим к единому виду.
#
# ВАЖНО про условия использования. ESPN и большинство изданий разрешают
# показывать только то, что пришло в самой ленте, обязательно со ссылкой
# на оригинал и с указанием источника; менять заголовки и аннотации нельзя.
# Поэтому мы храним текст ровно как он пришёл (убираем только HTML-теги,
# иначе его не показать), всегда сохраняем ссылку и название источника,
# а укорачиваем текст уже на экране средствами CSS, а не обрезкой в базе.

import re
import time
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.db import get_recent_titles, delete_news

# Ленты качаем сами, через httpx, и только потом отдаём в feedparser.
# Если позволить feedparser сходить по адресу самому, он представится своим
# служебным User-Agent — часть сайтов на это отвечает заглушкой.
client = httpx.Client(
    headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "ru,en;q=0.9",
    },
    timeout=30,
    follow_redirects=True,
    trust_env=False,
)

# Единую лигу узнаём по её названию и клубам. Сейчас не используется:
# лента ВТБ ниже посвящена только этому турниру. Оставлено на случай, если
# понадобится вылавливать её новости из общей баскетбольной ленты.
VTB_KEYWORDS = [
    "втб", "единая лига", "единой лиге", "единую лигу", "единой лиги",
    "цска", "уникс", "зенит", "локомотив-кубань", "локо",
    "уралмаш", "парма", "енисей", "мба", "самара", "автодор",
    "нижний новгород", "астана", "динамо",
]

# ===== Ленты по лигам =====
# name    — что показываем как источник
# url     — адрес ленты
# lang    — язык новостей
# filter  — берём новость, если встретилась ХОТЯ БЫ ОДНА из подстрок
# require — берём новость, только если встретились ВСЕ подстроки
#
# Оба фильтра ищут в заголовке, аннотации и ссылке. Нужны, когда лента шире
# нашей лиги: например, у CBS в ленте «NBA» попадается студенческий баскетбол,
# поэтому требуем раздел /nba/ в ссылке.
FEEDS = {
    "nba": [
        {"name": "Yahoo Sports", "lang": "en",
         "url": "https://sports.yahoo.com/nba/rss.xml"},
        # У CBS лента шире, чем НБА (попадается студенческий баскетбол).
        {"name": "CBS Sports", "lang": "en",
         "url": "https://www.cbssports.com/rss/headlines/nba/",
         "require": ["/nba/"]},
    ],
    "euroleague": [
        {"name": "Eurohoops", "lang": "en",
         "url": "https://www.eurohoops.net/en/feed/"},
    ],
    "vtb": [
        # Отдельная лента Единой лиги — фильтры не нужны, там только она.
        # Ссылку на неё «Чемпионат» даёт внизу страницы новостей турнира.
        {"name": "Чемпионат", "lang": "ru",
         "url": "https://www.championat.com/rss/news/basketball/vtbleague/"},
    ],
}

# Отключённые источники — чтобы не искать их заново:
#   ESPN NBA (espn.com/espn/rss/nba/news)  — отвечает 202 с пустым телом
#   Сайт Лиги ВТБ (vtb-league.com/feed/)   — отвечает 200 с пустым телом
#   HoopsHype                              — не разрешается по DNS
#   NBA.com, офиц. лента Евролиги          — 404, таких адресов нет
#   Sportando                              — итальянский язык
#   BasketNews                             — битый XML
#   Спортс (sports.ru/rss/all_news.xml)    — лента одна на весь сайт при 170+
#     новостях в день: в ней висит последний час, и баскетбол Единой лиги
#     туда попадает реже, чем мы её читаем. Не поломка — несовпадение
#     масштабов. Понадобится второй русский источник — искать выгрузку
#     по тегу турнира, а не общую ленту.
# Первые три открываются из других сетей: дело не в коде, а в блокировке.

# Сколько новостей берём из одной ленты за раз. Ленты отдают больше,
# а список в приложении листается кнопкой «Показать ещё» — так что
# запас лишним не будет.
PER_FEED_LIMIT = 40

# Насколько похожими должны быть заголовки, чтобы счесть их одной историей.
# Подобрано на реальных парах: при 0.5 склеиваются пересказы одной новости
# и при этом не склеиваются разные новости про один клуб.
SIMILARITY = 0.5

# Служебные слова, которые есть почти в любом заголовке и потому ничего
# не говорят о том, об одной ли истории речь.
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "says", "said", "after",
    "его", "она", "они", "как", "что", "для", "при", "под", "над", "это",
    "был", "была", "было", "если",
}


def _clean_text(raw: str) -> str:
    """Убирает HTML-теги из аннотации — сам текст оставляем как есть."""
    if not raw:
        return ""
    return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)


def _published_iso(entry) -> str:
    """Дата публикации в виде '2026-07-23T14:30:00'. Если её нет — берём
    текущую, чтобы новость не потерялась в конце списка."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc) \
            .strftime("%Y-%m-%dT%H:%M:%S")
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _image_url(entry):
    """Картинка новости, если источник её приложил. Лежать может в трёх
    разных местах — смотрим все, иначе оставляем пусто."""
    media = entry.get("media_content") or entry.get("media_thumbnail")
    if media and isinstance(media, list) and media[0].get("url"):
        return media[0]["url"]
    for link in (entry.get("links") or []):
        if str(link.get("type", "")).startswith("image/") and link.get("href"):
            return link["href"]
    return None


def _haystack(item: dict) -> str:
    return f"{item['title']} {item['summary']} {item['link']}".lower()


def _passes_filters(item: dict, feed: dict) -> bool:
    """Проверяет фильтры ленты: filter — хотя бы одно совпадение,
    require — все совпадения обязательны."""
    text = _haystack(item)

    required = feed.get("require")
    if required and not all(str(n).lower() in text for n in required):
        return False

    any_of = feed.get("filter")
    if any_of and not any(str(n).lower() in text for n in any_of):
        return False

    return True


# ===== Отсев повторов между источниками =====
def _tokens(title: str) -> set:
    """Значимые слова заголовка. Числа вынимаем отдельно, потому что одну
    и ту же сумму пишут по-разному: «$64M» и «$64 million»."""
    low = (title or "").lower()
    words = re.sub(r"[^\w\s]", " ", low).split()
    result = {w for w in words if len(w) >= 4 and w not in STOPWORDS}
    result |= set(re.findall(r"\d+", low))
    return result


def _similarity(tokens_a: set, tokens_b: set) -> float:
    """Доля общих слов от более короткого заголовка. Именно от короткого:
    краткая новость-«молния» и развёрнутая статья об одном событии тогда
    всё равно считаются похожими."""
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def drop_duplicates(items: list[dict], known: list[dict]) -> list[dict]:
    """Убирает повторы: одну историю пишут сразу несколько изданий.

    Сравниваем с уже лежащими в базе новостями (known) и между собой.
    Совпадение по ссылке повтором не считается — это просто та же самая
    новость при следующем обновлении, ей нужно дать обновиться.
    """
    seen = [(k["id"], _tokens(k["title"])) for k in known]

    result = []
    for item in items:
        item_tokens = _tokens(item["title"])
        duplicate = any(
            link != item["id"] and _similarity(item_tokens, tokens) >= SIMILARITY
            for link, tokens in seen
        )
        if duplicate:
            continue
        result.append(item)
        seen.append((item["id"], item_tokens))
    return result


def dedupe_stored(league_id: str) -> int:
    """Разбирает повторы среди УЖЕ сохранённых новостей.

    Нужна для новостей, попавших в базу до того, как появился отсев, и после
    добавления нового источника. Из каждой группы похожих оставляем самую
    свежую: get_recent_titles отдаёт записи от новых к старым, поэтому
    первая встреченная в группе и есть та, что нужно сохранить.
    """
    rows = get_recent_titles(league_id, limit=500)

    keep, extra = [], []
    for row in rows:
        row_tokens = _tokens(row["title"])
        if any(_similarity(row_tokens, kept) >= SIMILARITY for kept in keep):
            extra.append(row["id"])
        else:
            keep.append(row_tokens)

    return delete_news(extra)


def fetch_feed(league_id: str, feed: dict) -> list[dict]:
    """Одна лента -> список новостей в нашем формате.
    Ссылка служит идентификатором: одна и та же новость не задвоится."""
    response = client.get(feed["url"])
    response.raise_for_status()
    # response.content — уже распакованные байты (ленты часто отдают gzip)
    parsed = feedparser.parse(response.content)

    if not parsed.entries:
        # Показываем, что именно пришло вместо ленты: пустое тело и HTML-
        # заглушка выглядят одинаково «пусто», а причины у них разные.
        ctype = response.headers.get("content-type", "?")
        print(f"[новости] {feed['name']}: записей нет "
              f"(HTTP {response.status_code}, {ctype}, {len(response.content)} байт)")
        return []

    # ВАЖЕН ПОРЯДОК: сначала фильтруем ВСЮ ленту и только потом берём первые
    # PER_FEED_LIMIT штук. Если обрезать сразу, у широких лент (например,
    # у «Спортса» — одна лента на весь сайт) в первые записи попадают футбол
    # и хоккей, а до баскетбола дело просто не доходит.
    items = []
    for entry in parsed.entries:
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue                      # без ссылки и заголовка новость бесполезна
        item = {
            "id": link,
            "league_id": league_id,
            "title": title.strip(),
            "summary": _clean_text(entry.get("summary") or entry.get("description")),
            "link": link,
            "source": feed["name"],
            "published": _published_iso(entry),
            "image_url": _image_url(entry),
        }
        if _passes_filters(item, feed):
            items.append(item)
            if len(items) >= PER_FEED_LIMIT:
                break
    return items


def fetch_league(league_id: str) -> list[dict]:
    """Все новости лиги из всех её лент, без повторов. Упавшая лента не мешает
    остальным: ошибка пишется в консоль, и мы идём дальше (принцип ТЗ 6.4)."""
    collected = []
    for feed in FEEDS.get(league_id, []):
        try:
            items = fetch_feed(league_id, feed)
            print(f"[новости] {league_id} / {feed['name']}: получено {len(items)}")
            collected.append(items)
        except Exception as e:
            print(f"[новости] {league_id} / {feed['name']}: лента недоступна: {e}")

    # Сводим всё вместе, свежие сверху: при повторе останется самая свежая версия.
    flat = [item for items in collected for item in items]
    flat.sort(key=lambda x: x["published"], reverse=True)

    before = len(flat)
    flat = drop_duplicates(flat, get_recent_titles(league_id))
    if before != len(flat):
        print(f"[новости] {league_id}: отсеяно повторов — {before - len(flat)}")

    return flat