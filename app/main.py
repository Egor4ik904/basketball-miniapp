# app/main.py
# Главный файл: собирает наш веб-сервер (FastAPI).

import re
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.db import (
    init_db, migrate_db, get_connection,
    count_teams, save_teams, get_teams,
    get_team_ids, count_players, save_players,
    save_games, get_games, get_games_list, count_games, get_playoff_games,
    get_odds_for_games,
    count_standings, save_standings, get_standings,
    save_player_stats, get_player_stats,
    save_boxscore, get_boxscore,
    save_news, get_news, prune_news,
    get_meta, set_meta, clear_player_stats, set_league_season,
)
from app import news
from app import season as season_mod
from app import config
from app import bot as tg_bot
from app import userdata
from app import odds as odds_mod
from app.telegram_auth import verify_init_data
from app.adapters import nba, euroleague, vtb, vtbcup, nbacup
from app.brackets import build_bracket
from app.scheduler import start_scheduler

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# ===== Реестр адаптеров лиг =====
# Чтобы добавить новую лигу — пишем её адаптер и вписываем сюда одной строкой.
ADAPTERS = {
    "nba": nba,
    "euroleague": euroleague,
    "vtb": vtb,
    "vtbcup": vtbcup,      # Winline Basket Cup — под-турнир ВТБ (не плитка на
                          # главном; показывается вкладкой внутри ВТБ)
    "nbacup": nbacup,      # NBA Cup — под-турнир NBA (вкладка внутри NBA)
}

# Под-турниры: лиги, которые НЕ показываются плиткой на главном экране, а
# доступны как вкладка внутри «родительской» лиги. Ключ — под-турнир,
# значение — родитель.
SUBTOURNAMENTS = {
    "vtbcup": "vtb",
    "nbacup": "nba",
}


# ===== Проверка того, что приходит из адреса =====
# Идентификаторы из адреса попадают не только в запросы к базе (там они
# подставляются параметрами и безопасны), но и в АДРЕСА запросов к источникам:
# например, id матча становится частью пути. Без проверки через такой адрес
# можно было бы заставить наш сервер ходить куда угодно по чужому сайту.
# Поэтому пропускаем только то, что действительно похоже на идентификатор:
# «лига:код», где код — буквы, цифры, точка, дефис, подчёркивание.
# Идентификатор либо вида «лига:код» (nba:13, euroleague:MAD, nba:5104157),
# либо просто код лиги (nba, euroleague, vtb) — у лиги в избранном двоеточия
# и кода нет. Раньше двоеточие было обязательным, из-за чего добавление лиги
# в избранное отклонялось с ошибкой, хотя команды и игроки проходили.
ENTITY_ID_RE = re.compile(r"^[a-z]{2,20}(:[A-Za-z0-9_.-]{1,40})?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_entity_id(entity_id: str) -> str:
    if not ENTITY_ID_RE.match(entity_id or ""):
        raise HTTPException(status_code=400, detail="Некорректный идентификатор")
    return entity_id


def check_date(value: str) -> str:
    if not DATE_RE.match(value or ""):
        raise HTTPException(status_code=400, detail="Дата должна быть в виде ГГГГ-ММ-ДД")
    return value


def adapter_for(league_id: str):
    """Адаптер по id лиги (например 'nba')."""
    return ADAPTERS.get(league_id)


def adapter_for_entity(entity_id: str):
    """Адаптер по id сущности ('nba:401...' -> адаптер 'nba')."""
    return ADAPTERS.get(entity_id.split(":")[0])


def _warmup_fast_one(lid, adapter) -> None:
    """Быстрая загрузка ОДНОЙ лиги: команды, таблица, матчи, новости.
    Вынесено отдельно, чтобы гонять лиги параллельно (см. warmup_fast)."""
    try:
        if hasattr(adapter, "fetch_teams"):
            n = save_teams(adapter.fetch_teams())
            print(f"[старт] {lid}: команды обновлены — {n}")
    except Exception as e:
        print(f"[старт] {lid}: команды не загружены: {e}")

    try:
        if hasattr(adapter, "fetch_standings") and count_standings(lid) == 0:
            n = save_standings(adapter.fetch_standings())
            print(f"[старт] {lid}: загружена таблица ({n} строк)")
    except Exception as e:
        print(f"[старт] {lid}: таблица не загружена: {e}")

    try:
        if hasattr(adapter, "fetch_season_games") and count_games(lid) == 0:
            season_games = adapter.fetch_season_games()
            n = save_games(season_games)
            del season_games            # в базе уже есть — в памяти держать незачем
            print(f"[старт] {lid}: загружено матчей за сезон {n}")
    except Exception as e:
        print(f"[старт] {lid}: матчи сезона не загружены: {e}")

    try:
        n = save_news(news.fetch_league(lid))
        print(f"[старт] {lid}: новостей добавлено {n}")
    except Exception as e:
        print(f"[старт] {lid}: новости не загружены: {e}")


def warmup_fast() -> None:
    """БЫСТРАЯ часть прогрева: список лиг, таблицы, матчи, новости — то, что
    нужно для первых экранов. Лиги грузятся ПАРАЛЛЕЛЬНО (источники независимы),
    поэтому общее время примерно как у одной самой медленной лиги, а не сумма
    трёх. Составы — отдельно и потом, см. warmup_rosters."""
    import threading
    threads = []
    for lid, adapter in ADAPTERS.items():
        t = threading.Thread(target=_warmup_fast_one, args=(lid, adapter), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


def _warmup_rosters_one(lid, adapter) -> None:
    """Составы ОДНОЙ лиги. Пауза между командами небольшая — источник не
    завалить, но и не тянуть: лиги идут параллельно, на каждый источник
    поток запросов свой."""
    try:
        if hasattr(adapter, "fetch_roster") and count_players(lid) == 0:
            team_ids = get_team_ids(lid, season_mod.teams_season(lid))
            print(f"[старт] {lid}: загружаю составы {len(team_ids)} команд...")
            total, failed = 0, []
            for tid in team_ids:
                try:
                    total += save_players(adapter.fetch_roster(tid.split(":")[1]))
                except Exception as e:
                    failed.append(f"{tid} ({type(e).__name__})")
                time.sleep(0.15)
            print(f"[старт] {lid}: загружено игроков {total}"
                  + (f", не удалось: {', '.join(failed)}" if failed else ""))
    except Exception as e:
        print(f"[старт] {lid}: составы не загружены: {e}")


def warmup_rosters() -> None:
    """МЕДЛЕННАЯ часть: составы всех команд. Идёт последней, когда первые
    экраны уже готовы.

    Лиги грузятся ПОСЛЕДОВАТЕЛЬНО, по одной. Раньше было параллельно, но на
    бесплатном Render (512 МБ) три состава в памяти одновременно давали
    всплеск под лимит и перезапуск. По очереди — медленнее на минуту, зато
    память не скачет. Быстрая часть (warmup_fast) при этом остаётся
    параллельной, так что первые экраны появляются так же быстро."""
    for lid, adapter in ADAPTERS.items():
        _warmup_rosters_one(lid, adapter)


def sync_seasons() -> None:
    """Определяет текущий сезон каждой лиги и, если он сменился, чистит
    прошлогоднее. Вызывается до загрузки данных, чтобы всё поехало сразу
    из нужного сезона.

    Сбрасываем статистику игроков: она хранится без привязки к сезону,
    и без очистки в новом сезоне остались бы прошлогодние средние.
    Таблицу трогать не надо — она перезапишется по ключу «команда»,
    а матчи храним с полем season, они не мешают друг другу.
    """
    for lid in ADAPTERS:
        try:
            label = season_mod.label_for(lid)
            set_league_season(lid, label)

            key = f"season:{lid}"
            previous = get_meta(key)
            if previous and previous != label:
                removed = clear_player_stats(lid)
                print(f"[сезон] {lid}: сезон сменился ({previous} -> {label}), "
                      f"статистика игроков сброшена ({removed} записей)")
            set_meta(key, label)
        except Exception as e:
            print(f"[сезон] {lid}: определить не удалось: {e}")


def tidy_news() -> None:
    """Приводит новости в порядок перед загрузкой свежих:
    убирает материалы отключённых лент и разбирает накопившиеся повторы."""
    for lid, feeds in news.FEEDS.items():
        removed = prune_news(lid, [f["name"] for f in feeds])
        if removed:
            print(f"[старт] {lid}: убрано новостей отключённых источников — {removed}")

        duplicates = news.dedupe_stored(lid)
        if duplicates:
            print(f"[старт] {lid}: убрано повторов среди сохранённых — {duplicates}")


# Готовность приложения. Пока идёт первичный прогрев (составы, матчи сезона),
# страницы уже открываются, просто часть данных подъезжает следом. Флаг нужен,
# чтобы это состояние было видно на /api/health.
_warmup_done = threading.Event()


def _background_startup() -> None:
    """Долгая подготовка данных — в отдельном потоке, чтобы не задерживать
    открытие порта. На сервере (Render) проверка живости стучится по HTTP
    сразу после старта; если бы прогрев шёл до открытия порта, проверка бы
    не дождалась и сервис считался бы упавшим."""
    try:
        sync_seasons()
        tidy_news()
        warmup_fast()          # лиги, таблицы, матчи, новости — за секунды
    except Exception as e:
        print(f"[старт] быстрый прогрев прерван ошибкой: {e}")
    finally:
        # Помечаем готовность УЖЕ здесь: первые экраны наполнены, приложением
        # можно пользоваться. Составы догрузятся следом и не блокируют старт.
        _warmup_done.set()
        print("[старт] первичная подготовка завершена, приложение готово")

    # медленный хвост — составы. Идёт после отметки готовности.
    try:
        warmup_rosters()
        print("[старт] составы загружены")
    except Exception as e:
        print(f"[старт] загрузка составов прервана: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # выполняется один раз при запуске сервера
    print(f"[старт] настройки: {config.describe()}")
    print(f"[старт] настройки: {config.describe()}")
    init_db()
    migrate_db()
    userdata.init_pool()          # база пользовательских данных (Neon)

    # прогрев — в фоне, порт открывается сразу
    threading.Thread(target=_background_startup, daemon=True).start()

    # планировщик обновлений. Боту и главному циклу планировщик отдаёт для
    # рассылки уведомлений (она асинхронная и должна идти в этом цикле).
    import asyncio
    loop = asyncio.get_running_loop()
    notify_bot = tg_bot.bot if config.bot_enabled() else None
    app.state.scheduler = start_scheduler(ADAPTERS, bot=notify_bot, loop=loop)

    # телеграм-бот: регистрируем вебхук, если задан токен
    if config.bot_enabled():
        try:
            await tg_bot.setup_webhook()
        except Exception as e:
            print(f"[бот] вебхук зарегистрировать не удалось: {e}")
    else:
        print("[бот] токен не задан — бот выключен, работает только сайт")

    yield

    # выполняется при остановке сервера
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    # Вебхук намеренно НЕ снимаем: пусть остаётся установленным между
    # перезапусками и деплоями. Снятие здесь раньше и приводило к тому, что
    # после деплоя бот замолкал.
    userdata.close_pool()


app = FastAPI(title="Баскетбольный центр", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ===== Кто это? Проверка пользователя Telegram =====
# initData приходит в заголовке X-Init-Data. Проверяем подпись и достаём id.
# Всё, что меняет избранное, идёт через эту зависимость — иначе нельзя
# доверять, от чьего имени запрос.
async def require_user(x_init_data: str | None = Header(default=None)) -> dict:
    if not userdata.available():
        raise HTTPException(status_code=503, detail="Избранное временно недоступно")
    user = verify_init_data(x_init_data or "")
    if not user:
        raise HTTPException(status_code=401, detail="Не удалось подтвердить пользователя")
    userdata.ensure_user(user["id"], user.get("first_name"), user.get("username"))
    return user


class FavoriteIn(BaseModel):
    kind: str                      # team | league | player
    entity_id: str
    league_id: str | None = None
    label: str | None = None       # имя игрока/команды — чтобы показать в списке
    photo: str | None = None       # фото игрока — там же


class TeamPrefsIn(BaseModel):
    entity_id: str
    prefs: dict


@app.get("/api/favorites")
def get_favorites(user: dict = Depends(require_user)):
    return {"data": userdata.list_favorites(user["id"])}


@app.get("/api/favorites/ids")
def get_favorite_ids(user: dict = Depends(require_user)):
    return {"data": userdata.favorite_ids(user["id"])}


@app.post("/api/favorites")
def add_favorite_endpoint(body: FavoriteIn, user: dict = Depends(require_user)):
    if body.kind not in ("team", "league", "player"):
        raise HTTPException(status_code=400, detail="Неизвестный тип избранного")
    check_entity_id(body.entity_id)
    ok = userdata.add_favorite(user["id"], body.kind, body.entity_id, body.league_id,
                               body.label, body.photo)
    return {"ok": ok}


@app.delete("/api/favorites")
def remove_favorite_endpoint(body: FavoriteIn, user: dict = Depends(require_user)):
    check_entity_id(body.entity_id)
    ok = userdata.remove_favorite(user["id"], body.kind, body.entity_id)
    return {"ok": ok}


@app.post("/api/favorites/team-prefs")
def set_team_prefs_endpoint(body: TeamPrefsIn, user: dict = Depends(require_user)):
    check_entity_id(body.entity_id)
    ok = userdata.set_team_prefs(user["id"], body.entity_id, body.prefs)
    if not ok:
        raise HTTPException(status_code=404, detail="Команда не в избранном")
    return {"ok": ok}


@app.post(tg_bot.WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Сюда Telegram присылает сообщения бота. Секрет проверяем дважды:
    он зашит в самом адресе (в пути) и приходит в заголовке — сверяем оба.

    Отвечаем Telegram сразу, а обработку сообщения ведём в фоне: так на
    холодном старте (сервер только проснулся) доставка не срывается по
    таймауту, и /start не теряется."""
    if config.WEBHOOK_SECRET and x_telegram_bot_api_secret_token != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Неверный секрет")
    payload = await request.json()
    # не ждём завершения обработки — запускаем её отдельной задачей
    import asyncio
    asyncio.create_task(tg_bot.handle_update(payload))
    return {"ok": True}


@app.get("/api/health")
def health():
    # ok — сервер жив (этого достаточно для проверки живости на сервере);
    # ready — первичный прогрев завершён и данные на месте.
    return {"status": "ok", "ready": _warmup_done.is_set()}


@app.get("/api/leagues")
def get_leagues():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, season_label FROM leagues "
        "WHERE is_active = 1 ORDER BY sort_order"
    ).fetchall()
    conn.close()
    return {"data": [dict(row) for row in rows]}


@app.get("/api/leagues/{lid}/subtournaments")
def get_subtournaments(lid: str):
    """Под-турниры лиги (например, кубок у ВТБ). Фронт по этому списку рисует
    переключатель «Чемпионат / Кубок». Пусто — переключателя нет."""
    check_entity_id(lid)
    subs = []
    for sub_id, parent in SUBTOURNAMENTS.items():
        if parent == lid:
            conn = get_connection()
            row = conn.execute("SELECT id, name FROM leagues WHERE id = ?", (sub_id,)).fetchone()
            conn.close()
            if row:
                subs.append({"id": row["id"], "name": row["name"]})
    return {"data": subs}


@app.get("/api/leagues/{lid}/teams")
def get_teams_endpoint(lid: str):
    """Команды лиги — участники текущего сезона. Клубы, выбывшие после
    прошлого сезона, остаются в базе (без них у таблицы прошлого сезона
    пропали бы названия), но в этот список не попадают."""
    return {"data": get_teams(lid, season_mod.teams_season(lid))}


@app.get("/api/teams/{tid}/roster")
def get_roster(tid: str):
    check_entity_id(tid)
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, position, number, height, weight, birth_date, photo_url "
        "FROM players WHERE team_id = ? ORDER BY name",
        (tid,),
    ).fetchall()
    conn.close()
    return {"data": [dict(row) for row in rows]}


def _attach_odds(games: list[dict]) -> list[dict]:
    """Прикрепляет коэффициенты к матчам, у которых они есть. Матч без
    коэффициентов остаётся как есть — никакого поля odds у него не появится,
    чтобы интерфейс не показывал ничего про коэффициенты."""
    if not games or not config.odds_enabled():
        return games
    import json
    ids = [g["id"] for g in games if g.get("id")]
    found = get_odds_for_games(ids)          # {game_id: json} только где есть
    for g in games:
        raw = found.get(g.get("id"))
        if raw:
            try:
                g["odds"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return games


@app.get("/api/leagues/{lid}/games/list")
def get_games_list_endpoint(lid: str, mode: str = "results",
                            limit: int = 30, offset: int = 0):
    """Списки матчей: mode='results' — сыгранные (новые сверху),
    mode='schedule' — предстоящие (ближайшие сверху). Страницами по limit."""
    limit = max(1, min(limit, 100))          # защита от слишком больших запросов
    result = get_games_list(lid, mode, limit, offset)
    if isinstance(result, dict) and "games" in result:
        result["games"] = _attach_odds(result["games"])
    return {"data": result}


@app.get("/api/leagues/{lid}/games")
def get_games_endpoint(lid: str, date: str | None = None):
    """Матчи за конкретный день. Списки берут данные из /games/list,
    а этот эндпоинт остаётся для точечных запросов по дате."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    check_date(date)

    games = get_games(lid, date)

    # Матчи сезона обычно уже лежат в базе после прогрева. Но если по этой дате
    # ничего нет (например, база только что создана), догружаем разово.
    adapter = adapter_for(lid)
    if not games and adapter and hasattr(adapter, "fetch_games"):
        try:
            save_games(adapter.fetch_games(date.replace("-", "")))
            games = get_games(lid, date)
        except Exception as e:
            print(f"[games] {lid}: матчи за {date} не загружены: {e}")

    return {"data": games}


@app.get("/api/leagues/{lid}/bracket")
def get_bracket_endpoint(lid: str):
    """Сетка плей-офф: список кругов, в каждом — серии со счётом и матчами.
    Пустой список означает, что плей-офф ещё не начался."""
    return {"data": build_bracket(get_playoff_games(lid))}


@app.get("/api/leagues/{lid}/news")
def get_news_endpoint(lid: str, limit: int = 20, offset: int = 0):
    """Новости лиги страницами, свежие сверху."""
    limit = max(1, min(limit, 50))
    return {"data": get_news(lid, limit, offset)}


@app.get("/api/leagues/{lid}/standings")
def get_standings_endpoint(lid: str):
    return {"data": get_standings(lid)}


@app.get("/api/players/{pid}/stats")
def get_player_stats_endpoint(pid: str):
    check_entity_id(pid)
    stats = get_player_stats(pid)

    adapter = adapter_for_entity(pid)
    if stats is None and adapter and hasattr(adapter, "fetch_player_stats"):
        try:
            fetched = adapter.fetch_player_stats(pid.split(":")[1])
            if fetched:
                save_player_stats(fetched)
                stats = get_player_stats(pid)
        except Exception as e:
            print(f"[stats] {pid}: статистика не загружена: {e}")

    return {"data": stats}


@app.get("/api/games/{gid}/boxscore")
def get_boxscore_endpoint(gid: str):
    check_entity_id(gid)
    # берём статус и команды матча из нашей базы
    conn = get_connection()
    grow = conn.execute(
        "SELECT status, home_team_id, away_team_id FROM games WHERE id = ?", (gid,)
    ).fetchone()
    conn.close()
    status = grow["status"] if grow else None

    box = None
    if status == "final":
        box = get_boxscore(gid)          # из кеша (если уже сохраняли)

    if box is None:
        adapter = adapter_for_entity(gid)
        if adapter and hasattr(adapter, "fetch_boxscore"):
            try:
                box = adapter.fetch_boxscore(gid.split(":")[1])
                if status == "final":
                    save_boxscore(gid, box)
            except Exception as e:
                print(f"[boxscore] {gid}: не загружен: {e}")

    # Подставляем логотипы (и названия) команд из базы — те же, что в списке
    # матчей. Сопоставляем по home/away с командами этого матча.
    if box and box.get("teams") and grow:
        conn = get_connection()
        for role, tid in (("home", grow["home_team_id"]), ("away", grow["away_team_id"])):
            trow = conn.execute(
                "SELECT name, logo_url FROM teams WHERE id = ?", (tid,)
            ).fetchone()
            if trow and trow["logo_url"]:
                for team in box["teams"]:
                    if team.get("home_away") == role:
                        team["logo"] = trow["logo_url"]
                        if not team.get("name"):
                            team["name"] = trow["name"]
        conn.close()

    return {"data": box}