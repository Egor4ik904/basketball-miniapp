# app/telegram_auth.py
# Проверка подписи initData из Telegram Mini App.
#
# Когда приложение открывается внутри Telegram, оно получает строку initData —
# сведения о пользователе (id, имя), подписанные секретом на основе токена бота.
# Любой запрос, меняющий данные пользователя (добавить в избранное, настроить
# уведомления), должен приходить с этой строкой, а сервер обязан проверить
# подпись. Иначе кто угодно мог бы назваться чужим id и, например, подписать
# чужой аккаунт на уведомления.
#
# Алгоритм (официальная документация Telegram):
#   1. Разобрать initData как query-строку.
#   2. Отложить поле hash, остальные пары отсортировать по ключу.
#   3. Склеить их как "key=value", по одной на строку, через перевод строки.
#   4. Ключ = HMAC-SHA256(токен_бота, ключевая_строка "WebAppData").
#   5. HMAC-SHA256(строка из п.3, ключ из п.4) в hex сравнить с hash.
#   6. Дополнительно — не слишком ли старое auth_date (защита от повторной
#      отправки перехваченных данных).

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app import config

# Насколько свежим должен быть initData. Сутки — с запасом: Telegram обычно
# переотдаёт свежие данные при каждом открытии, но пользователь может держать
# приложение открытым долго, и рвать ему сессию раньше времени незачем.
MAX_AGE_SECONDS = 24 * 60 * 60


def verify_init_data(init_data: str, max_age: int = MAX_AGE_SECONDS) -> dict | None:
    """Проверяет подпись initData. Возвращает данные пользователя (dict),
    если подпись верна и данные свежие; иначе None.

    Отдаётся именно содержимое поля user — id и имя того, кто открыл
    приложение. Этому id можно доверять: подделать подпись без токена бота
    нельзя.
    """
    if not init_data or not config.BOT_TOKEN:
        return None

    # parse_qsl уже раскодирует проценты (%7B -> { и т.д.). Значения берём
    # именно раскодированными — так их подписывал Telegram.
    pairs = parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    # строка для проверки: пары без hash, отсортированы, через \n
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

    secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(),
                          hashlib.sha256).digest()
    calculated = hmac.new(secret_key, check_string.encode(),
                          hashlib.sha256).hexdigest()

    # сравнение, устойчивое к таймингам (не выходим раньше на первом отличии)
    if not hmac.compare_digest(calculated, received_hash):
        return None

    # защита от повторного использования старых данных
    auth_date = data.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > max_age:
                return None
        except ValueError:
            return None

    # поле user — это JSON-строка; разбираем
    user_raw = data.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None

    if not user.get("id"):
        return None
    return user