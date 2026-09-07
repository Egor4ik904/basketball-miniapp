# app/bot.py
# Телеграм-бот на aiogram. Живёт внутри того же веб-приложения (вариант с
# вебхуком): Telegram присылает сообщения на наш адрес, а не бот их опрашивает.
# Так на бесплатном хостинге не нужен отдельный постоянно живущий процесс.
#
# Что делает: по /start показывает кнопку, открывающую наше приложение прямо
# внутри Telegram (Mini App). Дальше весь интерфейс — уже знакомый веб-клиент.

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    MenuButtonWebApp,
)

from app import config

# Адрес вебхука на нашей стороне. Telegram будет слать сюда обновления.
# Секрет в пути — первый заслон: чужой, не знающий его, просто не попадёт
# на этот адрес.
WEBHOOK_PATH = f"/telegram/{config.WEBHOOK_SECRET}" if config.WEBHOOK_SECRET else "/telegram/webhook"

# Бот и диспетчер создаются, только если задан токен. Без него всё это
# не нужно — приложение работает как обычный сайт.
bot: Bot | None = None
dp: Dispatcher | None = None

if config.bot_enabled():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    def _app_keyboard() -> InlineKeyboardMarkup:
        """Кнопка, открывающая наше приложение внутри Telegram."""
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🏀 Открыть приложение",
                web_app=WebAppInfo(url=config.PUBLIC_URL),
            )
        ]])

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        name = message.from_user.first_name or "друг"
        await message.answer(
            f"Привет, {name}! 🏀\n\n"
            "<b>Баскетбольный центр</b> — три главные лиги в одном приложении:\n"
            "🇺🇸 NBA   🇪🇺 Евролига   🇷🇺 Единая лига ВТБ\n\n"
            "Здесь есть всё, чтобы следить за баскетболом:\n"
            "• турнирные таблицы и сетки плей-офф\n"
            "• результаты матчей и расписание\n"
            "• составы команд и статистика игроков\n"
            "• подробные протоколы матчей\n"
            "• свежие новости лиг\n"
            "• избранное и уведомления о матчах\n\n"
            "Доступно на 6 языках. Жми кнопку и погнали 👇",
            reply_markup=_app_keyboard(),
            parse_mode="HTML",
        )


async def setup_webhook() -> None:
    """Регистрирует вебхук в Telegram и ставит кнопку-меню приложения.
    Вызывается при старте сервера, если бот включён."""
    if not (bot and config.PUBLIC_URL):
        return

    url = f"{config.PUBLIC_URL}{WEBHOOK_PATH}"
    # secret_token — вторая проверка: Telegram будет слать его в заголовке
    # каждого запроса, а мы сверять. Так подделать обращение к вебхуку
    # не выйдет, даже зная адрес.
    await bot.set_webhook(
        url=url,
        secret_token=config.WEBHOOK_SECRET or None,
        # drop_pending_updates НЕ ставим: иначе сообщения, пришедшие пока
        # сервер на бесплатном хостинге просыпался, терялись бы — и /start
        # не доходил. Пусть Telegram досылает их после пробуждения.
        drop_pending_updates=False,
    )
    print(f"[бот] вебхук зарегистрирован: {url}")

    # Кнопка «Открыть приложение» слева от поля ввода — всегда под рукой.
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Открыть",
                web_app=WebAppInfo(url=config.PUBLIC_URL),
            )
        )
    except Exception as e:
        print(f"[бот] кнопку-меню поставить не удалось: {e}")


async def remove_webhook() -> None:
    """Снимает вебхук при остановке сервера."""
    if bot:
        try:
            await bot.delete_webhook()
        except Exception:
            pass


async def handle_update(payload: dict) -> None:
    """Передаёт одно обновление от Telegram в обработчики aiogram.
    Вызывается из веб-роутера, когда Telegram стучится на наш адрес.

    Ошибки ловим и логируем: обработка идёт в фоновой задаче, а у неё
    исключение иначе потерялось бы молча (и пользователь не понял бы, почему
    бот не ответил)."""
    if not (bot and dp):
        return
    try:
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        print(f"[бот] ошибка обработки обновления: {type(e).__name__}: {e}")