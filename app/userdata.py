# app/userdata.py
# Пользовательские данные в PostgreSQL (Neon): избранное и настройки
# уведомлений. Отдельно от основного кеша (матчи, новости), который лежит
# в SQLite: тот можно потерять и пересобрать, а подписки пользователей — нет,
# поэтому они в базе, переживающей перезапуски сервера.
#
# Если DATABASE_URL не задан, весь модуль работает вхолостую: функции просто
# ничего не делают. Так приложение запускается и локально без облачной базы —
# раздел избранного тогда недоступен, остальное работает.

import json

from app import config

# psycopg (v3) может быть не установлен на самой ранней стадии — тогда модуль
# не падает при импорте, а просто считает базу недоступной.
try:
    from psycopg_pool import ConnectionPool
    _HAS_DRIVER = True
except ImportError:
    _HAS_DRIVER = False

_pool = None


def available() -> bool:
    """Готова ли база к работе."""
    return bool(config.DATABASE_URL) and _HAS_DRIVER and _pool is not None


def init_pool() -> None:
    """Создаёт пул соединений и таблицы. Вызывается один раз при старте.
    Пул переиспользует соединения — на бесплатном тарифе Neon это важно,
    иначе можно упереться в лимит одновременных подключений."""
    global _pool
    if not config.DATABASE_URL:
        print("[userdata] DATABASE_URL не задан — избранное отключено")
        return
    if not _HAS_DRIVER:
        print("[userdata] psycopg не установлен — избранное отключено")
        return

    try:
        from psycopg_pool import ConnectionPool as _CP
        _pool = ConnectionPool(
            conninfo=config.DATABASE_URL,
            min_size=1,
            max_size=5,          # с запасом под бесплатный тариф
            timeout=15,
            # Neon на бесплатном тарифе засыпает при простое и закрывает
            # соединения со своей стороны. Без этих настроек пул хранил бы
            # «мёртвое» соединение и падал с AdminShutdown при следующем
            # запросе. check проверяет соединение ПЕРЕД выдачей и пересоздаёт
            # неживое; max_idle закрывает простаивающие раньше, чем их убьёт
            # Neon; попытки переподключения смягчают краткие обрывы.
            check=_CP.check_connection,
            max_idle=60,
            max_lifetime=300,
            reconnect_timeout=30,
            kwargs={"autocommit": True},
        )
        _pool.wait(timeout=15)
        _create_schema()
        print("[userdata] база пользователей подключена, таблицы готовы")
    except Exception as e:
        _pool = None
        print(f"[userdata] не удалось подключиться к базе: {e}")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _create_schema() -> None:
    with _pool.connection() as conn:
        # Пользователи. Ключ — telegram id (число, приходит из проверенного
        # initData). Имя держим для удобства, оно не обязательно.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id       BIGINT PRIMARY KEY,
                first_name  TEXT,
                username    TEXT,
                created_at  TIMESTAMPTZ DEFAULT now()
            )
        """)

        # Избранное. Одна строка — одна подписка. kind: team | league | player.
        # entity_id — наш обычный идентификатор ('nba:13', 'euroleague:MAD',
        # 'nba:401...'), league_id — к какой лиге относится (нужно для рассылки).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id          BIGSERIAL PRIMARY KEY,
                tg_id       BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                kind        TEXT NOT NULL,
                entity_id   TEXT NOT NULL,
                league_id   TEXT,
                label       TEXT,
                photo       TEXT,
                created_at  TIMESTAMPTZ DEFAULT now(),
                UNIQUE (tg_id, kind, entity_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites (tg_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fav_entity ON favorites (kind, entity_id)")
        # для баз, заведённых раньше: добавляем колонки, если их ещё нет
        conn.execute("ALTER TABLE favorites ADD COLUMN IF NOT EXISTS label TEXT")
        conn.execute("ALTER TABLE favorites ADD COLUMN IF NOT EXISTS photo TEXT")

        # Настройки уведомлений для КОМАНД. У команды пользователь выбирает
        # набор моментов: за час, за 30, за 10 минут, старт, финал. Храним
        # как JSON-объект флагов. У лиг и игроков режим фиксированный
        # (за 15 минут), поэтому им отдельные настройки не нужны.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS team_notify (
                tg_id       BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                entity_id   TEXT NOT NULL,
                prefs       JSONB NOT NULL,
                PRIMARY KEY (tg_id, entity_id)
            )
        """)

        # Журнал отправленных уведомлений. Фоновая задача крутится раз в минуту,
        # а условие «за час до матча» истинно все 60 минут подряд — без журнала
        # уведомление ушло бы 60 раз. Ключ уникальности: кому + про какой матч +
        # какой повод (hour/min30/min10/start/final/league/player). Раз отправив,
        # эту тройку сюда пишем и больше не повторяем.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_notifications (
                tg_id       BIGINT NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
                game_id     TEXT NOT NULL,
                moment      TEXT NOT NULL,
                sent_at     TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (tg_id, game_id, moment)
            )
        """)
        # Старые записи чистим по дате (матчи давно прошли) — отдельным индексом
        # по времени, чтобы удаление было быстрым.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sent_time ON sent_notifications (sent_at)")


# ===== Пользователи =====
def ensure_user(tg_id: int, first_name: str = None, username: str = None) -> None:
    """Заводит пользователя, если его ещё нет; обновляет имя, если поменялось."""
    if not available():
        return
    with _pool.connection() as conn:
        conn.execute("""
            INSERT INTO users (tg_id, first_name, username)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id) DO UPDATE
                SET first_name = EXCLUDED.first_name,
                    username   = EXCLUDED.username
        """, (tg_id, first_name, username))


# ===== Избранное =====
# По умолчанию для команды включаем «старт» и «финал» — самое ожидаемое.
DEFAULT_TEAM_PREFS = {
    "hour": False, "min30": False, "min10": False, "start": True, "final": True,
}


def add_favorite(tg_id: int, kind: str, entity_id: str, league_id: str = None,
                 label: str = None, photo: str = None) -> bool:
    if not available() or kind not in ("team", "league", "player"):
        return False
    with _pool.connection() as conn:
        conn.execute("""
            INSERT INTO favorites (tg_id, kind, entity_id, league_id, label, photo)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tg_id, kind, entity_id) DO NOTHING
        """, (tg_id, kind, entity_id, league_id, label, photo))
        # команде сразу заводим настройки уведомлений по умолчанию
        if kind == "team":
            conn.execute("""
                INSERT INTO team_notify (tg_id, entity_id, prefs)
                VALUES (%s, %s, %s)
                ON CONFLICT (tg_id, entity_id) DO NOTHING
            """, (tg_id, entity_id, json.dumps(DEFAULT_TEAM_PREFS)))
    return True


def remove_favorite(tg_id: int, kind: str, entity_id: str) -> bool:
    if not available():
        return False
    with _pool.connection() as conn:
        conn.execute(
            "DELETE FROM favorites WHERE tg_id = %s AND kind = %s AND entity_id = %s",
            (tg_id, kind, entity_id),
        )
        if kind == "team":
            conn.execute(
                "DELETE FROM team_notify WHERE tg_id = %s AND entity_id = %s",
                (tg_id, entity_id),
            )
    return True


def list_favorites(tg_id: int) -> list[dict]:
    """Все подписки пользователя. Для команд добавляем их настройки уведомлений."""
    if not available():
        return []
    with _pool.connection() as conn:
        rows = conn.execute("""
            SELECT f.kind, f.entity_id, f.league_id, f.label, f.photo, t.prefs
            FROM favorites f
            LEFT JOIN team_notify t
                   ON t.tg_id = f.tg_id AND t.entity_id = f.entity_id AND f.kind = 'team'
            WHERE f.tg_id = %s
            ORDER BY f.kind, f.created_at
        """, (tg_id,)).fetchall()

    result = []
    for kind, entity_id, league_id, label, photo, prefs in rows:
        item = {"kind": kind, "entity_id": entity_id, "league_id": league_id,
                "label": label, "photo": photo}
        if kind == "team":
            item["prefs"] = prefs if isinstance(prefs, dict) else DEFAULT_TEAM_PREFS
        result.append(item)
    return result


def favorite_ids(tg_id: int) -> list[str]:
    """Просто список entity_id, что в избранном, — чтобы фронт подсветил звёздочки.
    Формат элемента 'kind:entity_id', например 'team:nba:13'."""
    if not available():
        return []
    with _pool.connection() as conn:
        rows = conn.execute(
            "SELECT kind, entity_id FROM favorites WHERE tg_id = %s", (tg_id,)
        ).fetchall()
    return [f"{kind}:{entity_id}" for kind, entity_id in rows]


def all_favorites_for_notify() -> list[dict]:
    """Все подписки всех пользователей — по ним фоновая задача решает, кому
    что слать. Для команд прикладываем их настройки уведомлений.
    Отдаём плоский список: [{tg_id, kind, entity_id, league_id, prefs}]."""
    if not available():
        return []
    with _pool.connection() as conn:
        rows = conn.execute("""
            SELECT f.tg_id, f.kind, f.entity_id, f.league_id, t.prefs
            FROM favorites f
            LEFT JOIN team_notify t
                   ON t.tg_id = f.tg_id AND t.entity_id = f.entity_id AND f.kind = 'team'
        """).fetchall()
    result = []
    for tg_id, kind, entity_id, league_id, prefs in rows:
        item = {"tg_id": tg_id, "kind": kind, "entity_id": entity_id,
                "league_id": league_id}
        if kind == "team":
            item["prefs"] = prefs if isinstance(prefs, dict) else DEFAULT_TEAM_PREFS
        result.append(item)
    return result


def was_sent(tg_id: int, game_id: str, moment: str) -> bool:
    """Уже отправляли это уведомление?"""
    if not available():
        return True                # без базы считаем «отправлено», чтобы не слать
    with _pool.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_notifications WHERE tg_id=%s AND game_id=%s AND moment=%s",
            (tg_id, game_id, moment),
        ).fetchone()
    return bool(row)


def mark_sent(tg_id: int, game_id: str, moment: str) -> None:
    """Отмечает уведомление как отправленное."""
    if not available():
        return
    with _pool.connection() as conn:
        conn.execute("""
            INSERT INTO sent_notifications (tg_id, game_id, moment)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id, game_id, moment) DO NOTHING
        """, (tg_id, game_id, moment))


def cleanup_sent(days: int = 3) -> int:
    """Убирает записи об уведомлениях старше нескольких дней — матчи давно
    прошли, хранить незачем. Возвращает, сколько удалено."""
    if not available():
        return 0
    with _pool.connection() as conn:
        cur = conn.execute(
            "DELETE FROM sent_notifications WHERE sent_at < now() - make_interval(days => %s)",
            (days,),
        )
        return cur.rowcount


def set_team_prefs(tg_id: int, entity_id: str, prefs: dict) -> bool:
    """Обновляет набор моментов уведомлений для команды из избранного."""
    if not available():
        return False
    # оставляем только известные флаги, приводим к bool
    clean = {k: bool(prefs.get(k, False)) for k in DEFAULT_TEAM_PREFS}
    with _pool.connection() as conn:
        # настроить можно только команду, которая действительно в избранном
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE tg_id = %s AND kind = 'team' AND entity_id = %s",
            (tg_id, entity_id),
        ).fetchone()
        if not row:
            return False
        conn.execute("""
            INSERT INTO team_notify (tg_id, entity_id, prefs)
            VALUES (%s, %s, %s)
            ON CONFLICT (tg_id, entity_id) DO UPDATE SET prefs = EXCLUDED.prefs
        """, (tg_id, entity_id, json.dumps(clean)))
    return True