# app/db.py
# Всё, что связано с базой данных SQLite.

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "basketball.db"


def get_connection() -> sqlite3.Connection:
    """Соединение с базой. row_factory — читаем данные по именам колонок."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создаёт таблицы (если их нет) и добавляет три наши лиги."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leagues (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            logo_url     TEXT,
            season_label TEXT,
            sort_order   INTEGER,
            is_active    INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id         TEXT PRIMARY KEY,
            league_id  TEXT,
            season     TEXT,
            name       TEXT,
            short_name TEXT,
            city       TEXT,
            arena      TEXT,
            founded    TEXT,
            logo_url   TEXT,
            conference TEXT,
            division   TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id          TEXT PRIMARY KEY,
            team_id     TEXT,
            name        TEXT,
            position    TEXT,
            number      TEXT,
            height      TEXT,
            weight      TEXT,
            birth_date  TEXT,
            nationality TEXT,
            photo_url   TEXT
        )
    """)

    # Новые базы создаются сразу со всеми колонками; старые догоняет migrate_db().
    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id           TEXT PRIMARY KEY,
            league_id    TEXT,
            season       TEXT,
            game_date    TEXT,
            datetime     TEXT,
            status       TEXT,
            home_team_id TEXT,
            away_team_id TEXT,
            home_score   TEXT,
            away_score   TEXT,
            period       INTEGER,
            clock        TEXT,
            stage        TEXT,
            stage_label  TEXT,
            series_key   TEXT,
            series_round INTEGER,
            round_label  TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS standings (
            team_id    TEXT PRIMARY KEY,
            league_id  TEXT,
            conference TEXT,
            rank       INTEGER,
            wins       INTEGER,
            losses     INTEGER,
            win_pct    REAL,
            games_back TEXT,
            streak     TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_stats (
            player_id    TEXT PRIMARY KEY,
            games_played TEXT,
            minutes      TEXT,
            pts          TEXT,
            reb          TEXT,
            ast          TEXT,
            stl          TEXT,
            blk          TEXT,
            tov          TEXT,
            pf           TEXT,
            fg_pct       TEXT,
            fg3_pct      TEXT,
            ft_pct       TEXT
        )
    """)

    # Кеш box score матча (храним как JSON-строку).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS boxscores (
            game_id TEXT PRIMARY KEY,
            data    TEXT
        )
    """)

    # Служебные пары «ключ-значение»: например, какой сезон был при прошлом
    # запуске. По ним понимаем, что сезон сменился, и чистим прошлогоднее.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Новости лиг. Ключ — ссылка на оригинал: одна новость не задвоится,
    # даже если попадёт в несколько лент сразу.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id         TEXT PRIMARY KEY,
            league_id  TEXT,
            title      TEXT,
            summary    TEXT,
            link       TEXT,
            source     TEXT,
            published  TEXT,
            image_url  TEXT
        )
    """)

    leagues = [
        ("nba",        "NBA",             "2025/26", 1),
        ("euroleague", "Евролига",        "2025/26", 2),
        ("vtb",        "Единая лига ВТБ", "2025/26", 3),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO leagues (id, name, season_label, sort_order)
        VALUES (?, ?, ?, ?)
    """, leagues)

    conn.commit()
    conn.close()


# Колонки таблицы games, добавленные после первой версии базы.
# Нужны тем, у кого basketball.db уже создан старой схемой.
GAME_NEW_COLUMNS = {
    "season":       "TEXT",
    "stage":        "TEXT",
    "stage_label":  "TEXT",
    "series_key":   "TEXT",
    "series_round": "INTEGER",
    "round_label":  "TEXT",
}


def migrate_db() -> None:
    """Догоняет схему базы до актуальной, не трогая уже сохранённые данные.
    Безопасно вызывать при каждом старте: колонка добавляется только если её нет."""
    conn = get_connection()
    cur = conn.cursor()

    existing = {row["name"] for row in cur.execute("PRAGMA table_info(games)")}
    for name, col_type in GAME_NEW_COLUMNS.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE games ADD COLUMN {name} {col_type}")
            print(f"[база] в таблицу games добавлена колонка {name}")

    # У команд появился сезон: по нему отличаем участников нового сезона
    # от прошлогодних, не удаляя старых (иначе в таблице прошлого сезона
    # у выбывших клубов пропадут названия и логотипы).
    team_columns = {row["name"] for row in cur.execute("PRAGMA table_info(teams)")}
    if "season" not in team_columns:
        cur.execute("ALTER TABLE teams ADD COLUMN season TEXT")
        print("[база] в таблицу teams добавлена колонка season")

    # Матчей теперь тысячи, и выбираем мы их постоянно — без индексов будет медленно.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_games_league_date ON games (league_id, game_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_games_series ON games (league_id, series_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_news_league ON news (league_id, published)")

    conn.commit()
    conn.close()


def count_teams(league_id: str) -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM teams WHERE league_id = ?", (league_id,)).fetchone()
    conn.close()
    return row[0]


TEAM_FIELDS = ("id", "league_id", "season", "name", "short_name", "city", "logo_url")


def save_teams(teams: list[dict]) -> int:
    columns = ", ".join(TEAM_FIELDS)
    placeholders = ", ".join(":" + f for f in TEAM_FIELDS)

    conn = get_connection()
    cur = conn.cursor()
    for team in teams:
        cur.execute(
            f"INSERT OR REPLACE INTO teams ({columns}) VALUES ({placeholders})",
            {f: team.get(f) for f in TEAM_FIELDS},
        )
    conn.commit()
    conn.close()
    return len(teams)


def get_teams(league_id: str, season: str | None = None) -> list[dict]:
    """Команды лиги. Если задан сезон и такие команды есть — только они,
    иначе все (у NBA сезон не проставляется, там состав лиги постоянный)."""
    conn = get_connection()
    rows = []
    if season:
        rows = conn.execute(
            "SELECT id, name, short_name, city, logo_url FROM teams "
            "WHERE league_id = ? AND season = ? ORDER BY name",
            (league_id, season),
        ).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT id, name, short_name, city, logo_url FROM teams "
            "WHERE league_id = ? ORDER BY name",
            (league_id,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_team_ids(league_id: str, season: str | None = None) -> list[str]:
    """Идентификаторы команд лиги — по ним загружаются составы.
    С указанием сезона берём только его участников, чтобы не спрашивать
    заявки у клубов, которые в этом сезоне не играют."""
    return [team["id"] for team in get_teams(league_id, season)]


def count_players(league_id: str) -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM players WHERE team_id LIKE ?", (f"{league_id}:%",)).fetchone()
    conn.close()
    return row[0]


def save_players(players: list[dict]) -> int:
    conn = get_connection()
    cur = conn.cursor()
    for p in players:
        cur.execute("""
            INSERT OR REPLACE INTO players
                (id, team_id, name, position, number, height, weight, birth_date, photo_url)
            VALUES (:id, :team_id, :name, :position, :number, :height, :weight, :birth_date, :photo_url)
        """, p)
    conn.commit()
    conn.close()
    return len(players)


# Поля матча, которые умеем сохранять. Значения берутся через .get(), поэтому
# адаптер может отдать неполный набор — записи просто останутся пустыми,
# а не вызовут ошибку.
GAME_FIELDS = (
    "id", "league_id", "season", "game_date", "datetime", "status",
    "home_team_id", "away_team_id", "home_score", "away_score",
    "period", "clock",
    "stage", "stage_label", "series_key", "series_round", "round_label",
)


def save_games(games: list[dict]) -> int:
    columns = ", ".join(GAME_FIELDS)
    placeholders = ", ".join(":" + field for field in GAME_FIELDS)

    conn = get_connection()
    cur = conn.cursor()
    for g in games:
        row = {field: g.get(field) for field in GAME_FIELDS}
        cur.execute(
            f"INSERT OR REPLACE INTO games ({columns}) VALUES ({placeholders})", row
        )
    conn.commit()
    conn.close()
    return len(games)


def count_games(league_id: str) -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM games WHERE league_id = ?", (league_id,)).fetchone()
    conn.close()
    return row[0]


def get_games(league_id: str, game_date: str) -> list[dict]:
    """Матчи лиги за игровой день, с названиями и логотипами команд."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT g.id, g.game_date, g.datetime, g.status,
               g.home_score, g.away_score, g.period, g.clock,
               g.stage, g.stage_label, g.round_label,
               g.home_team_id, ht.name AS home_name, ht.short_name AS home_short, ht.logo_url AS home_logo,
               g.away_team_id, at.name AS away_name, at.short_name AS away_short, at.logo_url AS away_logo
        FROM games g
        LEFT JOIN teams ht ON ht.id = g.home_team_id
        LEFT JOIN teams at ON at.id = g.away_team_id
        WHERE g.league_id = ? AND g.game_date = ?
        ORDER BY g.datetime
    """, (league_id, game_date)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_games_list(league_id: str, mode: str, limit: int, offset: int) -> dict:
    """Список матчей лиги для вкладок «Результаты» и «Календарь».

    mode='results'  — сыгранные матчи, новые сверху;
    mode='schedule' — предстоящие (и идущие сейчас), ближайшие сверху.

    Возвращает {'games': [...], 'has_more': bool}. Чтобы понять, есть ли ещё
    страница, запрашиваем на одну запись больше, чем нужно, и лишнюю отбрасываем.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if mode == "schedule":
        where = "g.league_id = ? AND g.status != 'final' AND g.game_date >= ?"
        params = [league_id, today]
        order = "ASC"
    else:
        where = "g.league_id = ? AND g.status = 'final'"
        params = [league_id]
        order = "DESC"

    params += [limit + 1, offset]

    conn = get_connection()
    rows = conn.execute(f"""
        SELECT g.id, g.game_date, g.datetime, g.status,
               g.home_score, g.away_score, g.period, g.clock,
               g.stage, g.stage_label, g.round_label,
               g.home_team_id, ht.name AS home_name, ht.short_name AS home_short,
               ht.logo_url AS home_logo,
               g.away_team_id, at.name AS away_name, at.short_name AS away_short,
               at.logo_url AS away_logo
        FROM games g
        LEFT JOIN teams ht ON ht.id = g.home_team_id
        LEFT JOIN teams at ON at.id = g.away_team_id
        WHERE {where}
        ORDER BY g.datetime {order}
        LIMIT ? OFFSET ?
    """, params).fetchall()
    conn.close()

    games = [dict(row) for row in rows]
    has_more = len(games) > limit
    return {"games": games[:limit], "has_more": has_more}


def get_playoff_games(league_id: str) -> list[dict]:
    """Все матчи плей-офф и плей-ина лиги — сырьё для сетки.

    Кроме самих матчей подтягиваем из таблицы место и конференцию обеих команд:
    по ним сетка сортируется (сверху пары с лучшим посевом) и делится на
    Восток / Запад у NBA.

    Отсортированы по кругу, серии и времени, чтобы игры внутри серии шли по порядку."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT g.id, g.game_date, g.datetime, g.status,
               g.home_score, g.away_score,
               g.stage, g.stage_label, g.series_key, g.series_round,
               g.home_team_id, ht.name AS home_name, ht.short_name AS home_short,
               ht.logo_url AS home_logo,
               hst.rank AS home_seed, hst.conference AS home_conf,
               g.away_team_id, at.name AS away_name, at.short_name AS away_short,
               at.logo_url AS away_logo,
               ast.rank AS away_seed, ast.conference AS away_conf
        FROM games g
        LEFT JOIN teams ht ON ht.id = g.home_team_id
        LEFT JOIN teams at ON at.id = g.away_team_id
        LEFT JOIN standings hst ON hst.team_id = g.home_team_id
        LEFT JOIN standings ast ON ast.team_id = g.away_team_id
        WHERE g.league_id = ? AND g.series_key IS NOT NULL
        ORDER BY g.series_round, g.series_key, g.datetime
    """, (league_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def count_standings(league_id: str) -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM standings WHERE league_id = ?", (league_id,)).fetchone()
    conn.close()
    return row[0]


def save_standings(rows: list[dict]) -> int:
    conn = get_connection()
    cur = conn.cursor()
    for r in rows:
        cur.execute("""
            INSERT OR REPLACE INTO standings
                (team_id, league_id, conference, rank, wins, losses, win_pct, games_back, streak)
            VALUES (:team_id, :league_id, :conference, :rank, :wins, :losses, :win_pct, :games_back, :streak)
        """, r)
    conn.commit()
    conn.close()
    return len(rows)


def get_standings(league_id: str) -> list[dict]:
    """Турнирная таблица лиги с названиями и логотипами, по конференциям и местам."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.team_id, s.conference, s.rank, s.wins, s.losses, s.win_pct, s.games_back, s.streak,
               t.name AS team_name, t.short_name AS team_short, t.logo_url AS team_logo
        FROM standings s
        LEFT JOIN teams t ON t.id = s.team_id
        WHERE s.league_id = ?
        ORDER BY s.conference, s.rank
    """, (league_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_player_stats(stats: dict) -> None:
    """Сохраняет статистику одного игрока."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO player_stats
            (player_id, games_played, minutes, pts, reb, ast, stl, blk, tov, pf, fg_pct, fg3_pct, ft_pct)
        VALUES (:player_id, :games_played, :minutes, :pts, :reb, :ast, :stl, :blk, :tov, :pf, :fg_pct, :fg3_pct, :ft_pct)
    """, stats)
    conn.commit()
    conn.close()


def get_player_stats(player_id: str) -> dict | None:
    """Статистика игрока вместе с его данными (имя, позиция, фото). None, если нет."""
    conn = get_connection()
    row = conn.execute("""
        SELECT s.*, p.name, p.position, p.number, p.height, p.weight, p.photo_url, p.team_id
        FROM player_stats s
        LEFT JOIN players p ON p.id = s.player_id
        WHERE s.player_id = ?
    """, (player_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_boxscore(game_id: str, box: dict) -> None:
    """Сохраняет box score матча (как JSON)."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO boxscores (game_id, data) VALUES (?, ?)",
        (game_id, json.dumps(box, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def get_boxscore(game_id: str) -> dict | None:
    """Достаёт сохранённый box score матча. None, если его ещё нет."""
    conn = get_connection()
    row = conn.execute(
        "SELECT data FROM boxscores WHERE game_id = ?", (game_id,)
    ).fetchone()
    conn.close()
    return json.loads(row["data"]) if row else None


NEWS_FIELDS = ("id", "league_id", "title", "summary", "link",
               "source", "published", "image_url")


def save_news(items: list[dict]) -> int:
    """Сохраняет новости. Совпадения по ссылке перезаписываются, так что
    повторный разбор той же ленты не плодит дубликаты."""
    columns = ", ".join(NEWS_FIELDS)
    placeholders = ", ".join(":" + f for f in NEWS_FIELDS)

    conn = get_connection()
    cur = conn.cursor()
    for item in items:
        cur.execute(
            f"INSERT OR REPLACE INTO news ({columns}) VALUES ({placeholders})",
            {f: item.get(f) for f in NEWS_FIELDS},
        )
    conn.commit()
    conn.close()
    return len(items)


def count_news(league_id: str) -> int:
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) FROM news WHERE league_id = ?", (league_id,)).fetchone()
    conn.close()
    return row[0]


def get_news(league_id: str, limit: int, offset: int) -> dict:
    """Новости лиги страницами, свежие сверху.
    Как и в списках матчей, берём на одну запись больше — чтобы понять,
    осталось ли что-то ещё."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, title, summary, link, source, published, image_url
        FROM news
        WHERE league_id = ?
        ORDER BY published DESC
        LIMIT ? OFFSET ?
    """, (league_id, limit + 1, offset)).fetchall()
    conn.close()

    items = [dict(row) for row in rows]
    return {"news": items[:limit], "has_more": len(items) > limit}


def get_meta(key: str) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def clear_player_stats(league_id: str) -> int:
    """Удаляет статистику всех игроков лиги. Нужно при смене сезона: цифры
    должны считаться заново, а не продолжать прошлогодние."""
    conn = get_connection()
    cur = conn.execute("DELETE FROM player_stats WHERE player_id LIKE ?",
                       (f"{league_id}:%",))
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return removed


def get_stale_player_ids(league_id: str, limit: int = 60) -> list[str]:
    """Игроки лиги, чья статистика уже сохранена, — их и обновляем по кругу.
    Берём порциями, чтобы не заваливать источник запросами за один раз."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT player_id FROM player_stats WHERE player_id LIKE ? LIMIT ?",
        (f"{league_id}:%", limit),
    ).fetchall()
    conn.close()
    return [row["player_id"] for row in rows]


def set_league_season(league_id: str, label: str) -> None:
    """Обновляет подпись сезона на главном экране."""
    if not label:
        return
    conn = get_connection()
    conn.execute("UPDATE leagues SET season_label = ? WHERE id = ?", (label, league_id))
    conn.commit()
    conn.close()


def get_recent_titles(league_id: str, limit: int = 200) -> list[dict]:
    """Заголовки последних новостей лиги — нужны, чтобы отсеивать повторы
    между разными источниками (одну историю пишут все сразу)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, title FROM news WHERE league_id = ? ORDER BY published DESC LIMIT ?",
        (league_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_news(ids: list[str]) -> int:
    """Удаляет новости по списку ссылок (нужно для чистки повторов)."""
    if not ids:
        return 0
    conn = get_connection()
    marks = ", ".join("?" * len(ids))
    cur = conn.execute(f"DELETE FROM news WHERE id IN ({marks})", list(ids))
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return removed


def prune_news(league_id: str, keep_sources: list[str]) -> int:
    """Убирает из базы новости источников, которых больше нет в настройках.
    Благодаря этому достаточно удалить ленту из FEEDS — её старые новости
    уйдут сами, руками чистить базу не нужно."""
    conn = get_connection()
    if keep_sources:
        marks = ", ".join("?" * len(keep_sources))
        cur = conn.execute(
            f"DELETE FROM news WHERE league_id = ? AND source NOT IN ({marks})",
            [league_id] + list(keep_sources),
        )
    else:
        cur = conn.execute("DELETE FROM news WHERE league_id = ?", (league_id,))
    removed = cur.rowcount
    conn.commit()
    conn.close()
    return removed


def replace_team_players(team_id: str, players: list[dict]) -> int:
    """Полностью заменяет состав команды: удаляет прежних игроков этой команды
    и вставляет актуальных. Так из базы уходят те, кого больше нет в составе."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM players WHERE team_id = ?", (team_id,))
    for p in players:
        cur.execute("""
            INSERT OR REPLACE INTO players
                (id, team_id, name, position, number, height, weight, birth_date, photo_url)
            VALUES (:id, :team_id, :name, :position, :number, :height, :weight, :birth_date, :photo_url)
        """, p)
    conn.commit()
    conn.close()
    return len(players)