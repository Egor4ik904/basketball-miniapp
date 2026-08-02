// static/js/i18n.js
// Система перевода интерфейса. Тексты кнопок, заголовков и подписей больше не
// вшиты в код — они берутся отсюда по ключу через функцию t(). Данные из
// источников (имена команд, игроков, новости) не переводятся: они приходят
// от ESPN/EuroLeague/InfoBasket на своём языке.
//
// Добавить язык = добавить ещё один объект в TRANSLATIONS с теми же ключами.

const TRANSLATIONS = {
  ru: {
    // общее
    app_title: "🏀 Баскетбол",
    choose_league: "Выбери лигу",
    loading: "Загрузка…",
    show_more: "Показать ещё",
    pick_date: "Выбрать дату",
    back: "‹ Назад",

    // вкладки лиги
    tab_standings: "Таблица",
    tab_games: "Игры",
    tab_teams: "Команды",
    tab_players: "Игроки",
    tab_news: "Новости",

    // избранное
    favorites: "⭐ Избранное",
    favorites_sub: "Твои лиги, команды и игроки",
    fav_teams: "Команды",
    fav_leagues: "Лиги",
    fav_players: "Игроки",
    add_to_fav: "В избранное",
    in_fav: "★ В избранном",
    add_to_fav_btn: "☆ В избранное",
    remove_from_fav: "Убрать из избранного",
    fav_empty_leagues: "Нет избранных лиг. Добавь их звёздочкой на главной.",
    fav_empty_teams: "Нет избранных команд. Добавь их звёздочкой в списке команд лиги.",
    fav_empty_players: "Нет избранных игроков. Добавь их на карточке игрока.",
    league_notify_hint: "Уведомления за 15 минут до матчей лиги",
    player_stats_after: "статистика после матчей",

    // моменты уведомлений
    notify_hour: "За час",
    notify_min30: "За 30 мин",
    notify_min10: "За 10 мин",
    notify_start: "Старт матча",
    notify_final: "Финальный счёт",

    // статусы матча
    status_final: "Финал",
    status_live: "LIVE",
    today: "Сегодня",
    yesterday: "Вчера",
    tomorrow: "Завтра",

    // матчи
    games_expand: "Матчи ▾",
    games_collapse: "Матчи ▴",
    back_to_games: "‹ Матчи",
    back_to_playoff: "‹ Плей-офф",

    // конференции
    conf_east: "Восток",
    conf_west: "Запад",

    // статистика
    stat_points: "Очки",
    stat_rebounds: "Подборы",
    stat_assists: "Передачи",
    stat_steals: "Перехваты",
    stat_blocks: "Блоки",
    stat_turnovers: "Потери",
    stat_minutes: "Минуты",
    box_from: "ОТ",       // короткая подпись, если используется

    // коэффициенты
    odds_win: "Победа",
    odds_total: "Тотал",
    odds_handicap: "Фора",
    odds_over: "Б",
    odds_under: "М",

    // пустые состояния и ошибки
    empty_teams: "Команд пока нет.",
    empty_standings: "Таблицы пока нет (данные появятся в сезон).",
    empty_games_date: "На эту дату матчей нет.",
    empty_offseason: "Межсезонье — ближайших матчей пока нет. Загляни в «Результаты».",
    empty_played: "Сыгранных матчей пока нет.",
    empty_playoff: "Плей-офф ещё не начался.",
    empty_news: "Новостей пока нет.",
    empty_roster: "Состав пока не загружен.",
    empty_player_stats: "Статистики за сезон нет.",
    empty_boxscore: "Статистика матча недоступна.",
    series_not_started: "серия ещё не началась",
    series_finished: "серия завершена",
    err_leagues: "Не удалось загрузить лиги 😕",
    err_data: "Не удалось загрузить данные 😕",
    err_games: "Не удалось загрузить матчи 😕",
    err_news: "Не удалось загрузить новости 😕",
    err_roster: "Не удалось загрузить состав 😕",
    err_boxscore: "Не удалось загрузить статистику матча 😕",
    err_stats: "Не удалось загрузить статистику 😕",
    err_favorites: "Не удалось загрузить избранное 😕",

    // сезон
    season: "Сезон",

    // подвкладки и колонки, добавленные во втором проходе
    subtab_regular: "Регулярный чемпионат",
    subtab_playoff: "Плей-офф",
    subtab_results: "Результаты",
    subtab_schedule: "Календарь",
    box_team: "Команда",
    match_word: "Матч",
    // короткие заголовки колонок статистики (боксскор/таблица)
    col_min: "МИН",
    col_pts: "ОЧ",
    col_reb: "ПД",
    col_ast: "ПАС",
    col_stl: "ПХ",
    col_blk: "БЛ",
    col_to: "П",
    col_games: "И",
    col_wins: "В",
    col_pts_short: "ПТ",

    months: ["января","февраля","марта","апреля","мая","июня",
             "июля","августа","сентября","октября","ноября","декабря"],
    weekdays: ["воскресенье","понедельник","вторник","среда","четверг","пятница","суббота"],
  },

  en: {
    app_title: "🏀 Basketball",
    choose_league: "Choose a league",
    loading: "Loading…",
    show_more: "Show more",
    pick_date: "Pick a date",
    back: "‹ Back",

    tab_standings: "Standings",
    tab_games: "Games",
    tab_teams: "Teams",
    tab_players: "Players",
    tab_news: "News",

    favorites: "⭐ Favorites",
    favorites_sub: "Your leagues, teams and players",
    fav_teams: "Teams",
    fav_leagues: "Leagues",
    fav_players: "Players",
    add_to_fav: "Add to favorites",
    in_fav: "★ In favorites",
    add_to_fav_btn: "☆ Add to favorites",
    remove_from_fav: "Remove from favorites",
    fav_empty_leagues: "No favorite leagues yet. Add them with the star on the home screen.",
    fav_empty_teams: "No favorite teams yet. Add them with the star in a league's team list.",
    fav_empty_players: "No favorite players yet. Add them on a player's card.",
    league_notify_hint: "Notifications 15 minutes before the league's games",
    player_stats_after: "stats after games",

    notify_hour: "1 hour before",
    notify_min30: "30 min before",
    notify_min10: "10 min before",
    notify_start: "Game start",
    notify_final: "Final score",

    status_final: "Final",
    status_live: "LIVE",
    today: "Today",
    yesterday: "Yesterday",
    tomorrow: "Tomorrow",

    games_expand: "Games ▾",
    games_collapse: "Games ▴",
    back_to_games: "‹ Games",
    back_to_playoff: "‹ Playoffs",

    conf_east: "East",
    conf_west: "West",

    stat_points: "Points",
    stat_rebounds: "Rebounds",
    stat_assists: "Assists",
    stat_steals: "Steals",
    stat_blocks: "Blocks",
    stat_turnovers: "Turnovers",
    stat_minutes: "Minutes",
    box_from: "OT",

    odds_win: "Win",
    odds_total: "Total",
    odds_handicap: "Handicap",
    odds_over: "O",
    odds_under: "U",

    empty_teams: "No teams yet.",
    empty_standings: "No standings yet (they appear during the season).",
    empty_games_date: "No games on this date.",
    empty_offseason: "Off-season — no upcoming games yet. Check \"Results\".",
    empty_played: "No games played yet.",
    empty_playoff: "The playoffs haven't started yet.",
    empty_news: "No news yet.",
    empty_roster: "Roster not loaded yet.",
    empty_player_stats: "No stats for this season.",
    empty_boxscore: "Box score unavailable.",
    series_not_started: "series hasn't started",
    series_finished: "series finished",
    err_leagues: "Couldn't load leagues 😕",
    err_data: "Couldn't load data 😕",
    err_games: "Couldn't load games 😕",
    err_news: "Couldn't load news 😕",
    err_roster: "Couldn't load roster 😕",
    err_boxscore: "Couldn't load box score 😕",
    err_stats: "Couldn't load stats 😕",
    err_favorites: "Couldn't load favorites 😕",

    season: "Season",

    subtab_regular: "Regular season",
    subtab_playoff: "Playoffs",
    subtab_results: "Results",
    subtab_schedule: "Schedule",
    box_team: "Team",
    match_word: "Game",
    col_min: "MIN",
    col_pts: "PTS",
    col_reb: "REB",
    col_ast: "AST",
    col_stl: "STL",
    col_blk: "BLK",
    col_to: "TO",
    col_games: "G",
    col_wins: "W",
    col_pts_short: "PTS",

    months: ["January","February","March","April","May","June",
             "July","August","September","October","November","December"],
    weekdays: ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"],
  },
};

// Доступные языки для переключателя (порядок = порядок в меню).
const LANGUAGES = [
  { code: "ru", label: "Русский", flag: "🇷🇺" },
  { code: "en", label: "English", flag: "🇬🇧" },
];

// Текущий язык. Запоминаем в Telegram CloudStorage если есть, иначе в памяти.
// Язык по умолчанию — русский (можно позже брать из настроек Telegram).
let currentLang = "ru";

function setLang(code) {
  if (TRANSLATIONS[code]) {
    currentLang = code;
  }
}

function getLang() {
  return currentLang;
}

// Главная функция перевода: t("favorites") -> "⭐ Избранное" или "⭐ Favorites".
// Если ключа нет в текущем языке — берём русский, если и там нет — сам ключ
// (чтобы ничего не «пропало» на экране при опечатке в ключе).
function t(key) {
  const lang = TRANSLATIONS[currentLang] || TRANSLATIONS.ru;
  if (key in lang) return lang[key];
  if (key in TRANSLATIONS.ru) return TRANSLATIONS.ru[key];
  return key;
}