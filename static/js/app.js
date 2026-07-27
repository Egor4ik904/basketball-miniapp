// static/js/app.js
// Экраны: главная -> лига (вкладки) -> команда -> игрок; матч -> box score.
// Вкладка «Таблица» разделена на две: регулярный чемпионат и сетка плей-офф.

// ===== Безопасность вывода =====
// Разметку мы собираем строками, а данные приходят из чужих источников:
// заголовки новостей — из RSS, имена и названия — из API лиг. Если в них
// окажется HTML, браузер его выполнит. Поэтому ВСЁ, что подставляется
// в разметку, проходит через esc(), а ссылки — через safeUrl().
function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Пропускаем только http и https: ссылка вида javascript:... из чужой ленты
// выполнила бы код при нажатии.
function safeUrl(value) {
  const url = String(value || "").trim();
  return /^https?:\/\//i.test(url) ? url : "";
}

const root = document.getElementById("app");

// ===== Telegram Mini App =====
// Объект появляется, только когда приложение открыто внутри Telegram.
// Вне Telegram (обычный браузер) tg === undefined, и всё, что ниже, тихо
// пропускается — сайт работает как раньше.
const tg = window.Telegram && window.Telegram.WebApp;

// Стек возврата. Каждый переход на новый экран кладёт сюда функцию «как
// вернуться на предыдущий». И наша нарисованная кнопка «Назад», и системная
// кнопка Telegram снимают верхний элемент — поведение у них общее.
const backStack = [];

// ===== Избранное =====
// Работает только внутри Telegram: серверу нужна подпись initData, чтобы
// знать, кто добавляет. В обычном браузере подписи нет — звёздочки прячем.
const initData = tg ? tg.initData : "";
const favEnabled = !!(tg && initData);

// Множество избранного, чтобы звёздочки знали своё состояние без запроса на
// каждый экран. Элемент — строка "kind:entity_id", например "team:nba:13".
let favSet = new Set();

// Запросы к серверу с подписью в заголовке. Без initData сервер не поверит,
// кто мы, поэтому эти вызовы имеют смысл только в Telegram.
async function favApi(method, path, body) {
  const headers = { "X-Init-Data": initData };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error("fav " + res.status);
  return res.json();
}

// Один раз при запуске тянем список избранного и запоминаем.
async function loadFavorites() {
  if (!favEnabled) return;
  try {
    const data = await favApi("GET", "/api/favorites/ids");
    favSet = new Set((data && data.data) || []);
  } catch (e) {
    favSet = new Set();
  }
}

function favKey(kind, entityId) {
  return `${kind}:${entityId}`;
}

function isFav(kind, entityId) {
  return favSet.has(favKey(kind, entityId));
}

// Добавляет/убирает из избранного и держит локальное множество в согласии
// с сервером. Возвращает новое состояние (true — теперь в избранном).
async function toggleFav(kind, entityId, leagueId, extra) {
  const key = favKey(kind, entityId);
  const wasFav = favSet.has(key);
  try {
    if (wasFav) {
      await favApi("DELETE", "/api/favorites", { kind, entity_id: entityId });
      favSet.delete(key);
    } else {
      const body = { kind, entity_id: entityId, league_id: leagueId };
      if (extra && extra.label) body.label = extra.label;
      if (extra && extra.photo) body.photo = extra.photo;
      await favApi("POST", "/api/favorites", body);
      favSet.add(key);
    }
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
    return !wasFav;
  } catch (e) {
    return wasFav;                 // не вышло — состояние не меняем
  }
}

// Кнопка-звёздочка. Возвращает готовый элемент, сам переключает состояние.
// stopClick — не давать нажатию «протечь» на родительскую карточку (иначе
// тап по звезде ещё и откроет команду).
function makeStar(kind, entityId, leagueId, stopClick = true) {
  const btn = document.createElement("button");
  btn.className = "star" + (isFav(kind, entityId) ? " on" : "");
  btn.textContent = isFav(kind, entityId) ? "★" : "☆";
  btn.setAttribute("aria-label", "В избранное");
  const onTap = async (e) => {
    if (stopClick) { e.stopPropagation(); e.preventDefault(); }
    if (btn.disabled) return;
    btn.disabled = true;
    const nowFav = await toggleFav(kind, entityId, leagueId);
    btn.classList.toggle("on", nowFav);
    btn.textContent = nowFav ? "★" : "☆";
    btn.disabled = false;
  };
  // capture=true — обработчик звезды срабатывает раньше клика по карточке,
  // даже если сверху лежит другой элемент
  btn.addEventListener("click", onTap, true);
  return btn;
}

function goBack() {
  const step = backStack.pop();
  if (step) step();
  syncBackButton();
}

// Регистрирует экран в истории: fn — как вернуться на ТЕКУЩИЙ экран,
// перед тем как уйти на следующий.
function pushHistory(fn) {
  backStack.push(fn);
  syncBackButton();
}

function resetHistory() {
  backStack.length = 0;
  syncBackButton();
}

// Показывает или прячет системную кнопку «Назад» в шапке Telegram —
// смотря есть ли куда возвращаться.
function syncBackButton() {
  if (!tg || !tg.BackButton) return;
  if (backStack.length > 0) tg.BackButton.show();
  else tg.BackButton.hide();
}

function initTelegram() {
  if (!tg) return;                 // не в Telegram — выходим

  tg.ready();                      // сообщаем Telegram, что готовы
  tg.expand();                     // разворачиваем на всю высоту

  // Системная кнопка «Назад» делает то же, что наша нарисованная.
  if (tg.BackButton) {
    tg.BackButton.onClick(goBack);
  }

  applyTelegramTheme();
  // Тема может смениться на лету (пользователь переключил светлую/тёмную) —
  // подхватываем.
  tg.onEvent("themeChanged", applyTelegramTheme);
}

// Переносит цвета из темы Telegram в наши CSS-переменные, чтобы приложение
// выглядело как часть мессенджера, а не инородно. Если какого-то цвета
// Telegram не прислал, остаётся наш исходный из style.css.
function applyTelegramTheme() {
  if (!tg) return;
  const p = tg.themeParams || {};
  const root = document.documentElement.style;

  const map = {
    "--bg": p.bg_color,
    "--card": p.secondary_bg_color,
    "--text": p.text_color,
    "--muted": p.hint_color,
    "--accent": p.button_color,
  };
  for (const [name, value] of Object.entries(map)) {
    if (value) root.setProperty(name, value);
  }

  // «Поднятые» поверхности (карточки при наведении) делаем чуть светлее фона
  // карточки — в чужой теме подобрать точный оттенок нельзя, берём сам фон.
  if (p.secondary_bg_color) root.setProperty("--card-hover", p.secondary_bg_color);

  // Цвет шапки и фон окна Telegram — в тон приложению.
  try {
    if (p.bg_color) {
      tg.setHeaderColor(p.bg_color);
      tg.setBackgroundColor(p.bg_color);
    }
  } catch (e) { /* старые версии Telegram — не критично */ }
}

async function api(path) {
  const res = await fetch(path);
  const json = await res.json();
  return json.data;
}

// --- помощники для дат ---
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function addDays(dateStr, delta) {
  const d = new Date(dateStr + "T12:00:00");
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function formatShortDate(iso) {
  // '2026-06-12' -> '12.06'
  if (!iso || iso.length < 10) return "";
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

// Когда фотографии нет (новичок, которого источник ещё не снял),
// показываем кружок с инициалами — это лучше пустого места.
function initials(name) {
  return (name || "").trim().split(/\s+/).slice(0, 2)
    .map(part => part[0] || "").join("").toUpperCase();
}

function avatarHtml(person, className) {
  if (person.photo_url) {
    // если ссылка окажется битой, прячем картинку и остаётся кружок-подложка
    return `<img class="${className}" src="${safeUrl(person.photo_url)}" alt=""
                 onerror="this.style.visibility='hidden'">`;
  }
  return `<div class="${className} avatar-fallback">${esc(initials(person.name))}</div>`;
}

const MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
                   "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const WEEKDAYS_RU = ["воскресенье", "понедельник", "вторник", "среда",
                     "четверг", "пятница", "суббота"];

function formatDayTitle(iso) {
  // '2026-06-12' -> '12 июня, пятница' (для сегодня/вчера/завтра — словами)
  if (!iso || iso.length < 10) return "";
  const today = todayStr();
  const d = new Date(iso + "T12:00:00");
  const diff = Math.round((d - new Date(today + "T12:00:00")) / 86400000);
  if (diff === 0) return "Сегодня";
  if (diff === -1) return "Вчера";
  if (diff === 1) return "Завтра";
  return `${d.getDate()} ${MONTHS_RU[d.getMonth()]}, ${WEEKDAYS_RU[d.getDay()]}`;
}

// Как ESPN называет конференции -> как показываем мы.
const CONFERENCE_NAMES = {
  "Eastern Conference": "Восток",
  "Western Conference": "Запад",
};

let boxActiveTeam = 0;            // активная команда на экране матча
let standingsSubTab = "table";    // «table» или «bracket» внутри вкладки «Таблица»
let gamesSubTab = "results";      // «results», «schedule» или «date» внутри вкладки «Матчи»
let gamesDate = todayStr();       // выбранный день в режиме «Дата»
let gamesOffset = 0;              // сколько матчей уже показано (для «Показать ещё»)
const GAMES_PAGE = 30;            // размер страницы списка матчей
let newsOffset = 0;               // сколько новостей уже показано
const NEWS_PAGE = 20;             // размер страницы новостей

// ===== Главный экран: список лиг =====
async function showHome() {
  resetHistory();
  root.innerHTML = `
    <header class="app-header">
      <h1>🏀 Баскетбол</h1>
      <p class="subtitle">Выбери лигу</p>
    </header>
    <main class="container"><div id="leagues" class="muted">Загрузка…</div></main>
  `;
  try {
    const leagues = await api("/api/leagues");
    const box = document.getElementById("leagues");
    box.className = "card-list";
    box.innerHTML = "";
    for (const league of leagues) {
      const card = document.createElement("div");
      card.className = "league-card";
      card.innerHTML = `
        <div class="league-info">
          <div class="league-name">${esc(league.name)}</div>
          <div class="league-season">Сезон ${esc(league.season_label)}</div>
        </div>`;
      card.addEventListener("click", () => { pushHistory(showHome); showLeague(league); });

      const arrow = document.createElement("div");
      arrow.className = "arrow";
      arrow.textContent = "›";
      card.appendChild(arrow);

      // звезда лиги — абсолютно спозиционирована (одинаковое место у всех),
      // клик по ней не должен открывать лигу
      if (favEnabled) {
        const star = makeStar("league", league.id, league.id);
        star.classList.add("star-league");
        card.appendChild(star);
      }
      box.appendChild(card);
    }

    // кнопка «Избранное» под списком лиг
    if (favEnabled) {
      const favBtn = document.createElement("div");
      favBtn.className = "league-card fav-entry";
      favBtn.innerHTML = `
        <div class="league-info">
          <div class="league-name">⭐ Избранное</div>
          <div class="league-season">Твои лиги, команды и игроки</div>
        </div>
        <div class="arrow">›</div>`;
      favBtn.addEventListener("click", () => { pushHistory(showHome); showFavorites(); });
      box.appendChild(favBtn);
    }
  } catch (e) {
    document.getElementById("leagues").textContent = "Не удалось загрузить лиги 😕";
  }
}

// ===== Экран лиги: вкладки =====
function showLeague(league, activeTab = "standings") {
  root.innerHTML = `
    <header class="app-header">
      <button class="back" id="back">‹ Назад</button>
      <h1>${esc(league.name)}</h1>
    </header>
    <nav class="tabs">
      <button class="tab" data-tab="standings">Таблица</button>
      <button class="tab" data-tab="games">Матчи</button>
      <button class="tab" data-tab="news">Новости</button>
      <button class="tab" data-tab="teams">Команды</button>
    </nav>
    <main class="container"><div id="tab-content" class="muted">Загрузка…</div></main>
  `;
  document.getElementById("back").addEventListener("click", goBack);

  const tabs = root.querySelectorAll(".tab");
  tabs.forEach(tab => {
    if (tab.dataset.tab === activeTab) tab.classList.add("active");
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      openTab(league, tab.dataset.tab);
    });
  });
  openTab(league, activeTab);
}

async function openTab(league, tabName) {
  const content = document.getElementById("tab-content");
  content.className = "muted";
  content.textContent = "Загрузка…";

  if (tabName === "standings") {
    showStandingsTab(league);
  } else if (tabName === "teams") {
    renderTeams(await api(`/api/leagues/${league.id}/teams`), league);
  } else if (tabName === "games") {
    showGames(league);
  } else if (tabName === "news") {
    showNews(league);
  }
}

// ===== Вкладка «Таблица»: две под-вкладки =====
function showStandingsTab(league) {
  const content = document.getElementById("tab-content");
  content.className = "";
  content.innerHTML = `
    <div class="subtabs">
      <button class="subtab" data-sub="table">Регулярный чемпионат</button>
      <button class="subtab" data-sub="bracket">Плей-офф</button>
    </div>
    <div id="sub-content" class="muted">Загрузка…</div>
  `;

  const subtabs = content.querySelectorAll(".subtab");
  subtabs.forEach(btn => {
    if (btn.dataset.sub === standingsSubTab) btn.classList.add("active");
    btn.addEventListener("click", () => {
      standingsSubTab = btn.dataset.sub;
      subtabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      loadStandingsSub(league);
    });
  });

  loadStandingsSub(league);
}

async function loadStandingsSub(league) {
  const box = document.getElementById("sub-content");
  box.className = "muted";
  box.textContent = "Загрузка…";
  try {
    if (standingsSubTab === "bracket") {
      renderBracket(await api(`/api/leagues/${league.id}/bracket`), league);
    } else {
      renderStandings(await api(`/api/leagues/${league.id}/standings`));
    }
  } catch (e) {
    box.className = "muted";
    box.textContent = "Не удалось загрузить данные 😕";
  }
}

// ===== Под-вкладка «Регулярный чемпионат» =====
function renderStandings(standings) {
  const content = document.getElementById("sub-content");
  if (!standings || standings.length === 0) {
    content.className = "muted";
    content.textContent = "Таблицы пока нет (данные появятся в сезон).";
    return;
  }
  content.className = "";
  content.innerHTML = "";

  const byConf = {};
  for (const row of standings) {
    const c = row.conference || "Таблица";
    (byConf[c] = byConf[c] || []).push(row);
  }

  for (const conf of Object.keys(byConf)) {
    const title = document.createElement("h2");
    title.className = "section-title";
    title.textContent = CONFERENCE_NAMES[conf] || conf;
    content.appendChild(title);

    const table = document.createElement("div");
    table.className = "standings";
    table.innerHTML = `
      <div class="st-row st-head">
        <span class="st-rank">#</span><span class="st-team">Команда</span>
        <span class="st-num">В</span><span class="st-num">П</span>
      </div>`;
    for (const row of byConf[conf]) {
      const r = document.createElement("div");
      r.className = "st-row";
      r.innerHTML = `
        <span class="st-rank">${esc(row.rank)}</span>
        <span class="st-team"><img class="st-logo" src="${safeUrl(row.team_logo)}" alt="">${esc(row.team_short || row.team_name)}</span>
        <span class="st-num">${esc(row.wins)}</span>
        <span class="st-num">${esc(row.losses)}</span>`;
      table.appendChild(r);
    }
    content.appendChild(table);
  }
}

// ===== Под-вкладка «Плей-офф»: сетка =====
function renderBracket(rounds, league) {
  const box = document.getElementById("sub-content");
  if (!rounds || rounds.length === 0) {
    box.className = "muted";
    box.textContent = "Плей-офф ещё не начался.";
    return;
  }
  box.className = "";
  box.innerHTML = "";

  for (const round of rounds) {
    const title = document.createElement("h2");
    title.className = "section-title";
    title.textContent = round.label;
    box.appendChild(title);

    // Внутри круга серии делим по конференциям (у NBA — Восток / Запад).
    // Если конференций нет или она одна, заголовки не показываем.
    const groups = new Map();
    for (const series of round.series) {
      const key = series.conference || "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(series);
    }
    const showConfTitles = groups.size > 1;

    for (const [conference, list] of groups) {
      if (showConfTitles && conference) {
        const sub = document.createElement("div");
        sub.className = "conf-title";
        sub.textContent = CONFERENCE_NAMES[conference] || conference;
        box.appendChild(sub);
      }
      for (const series of list) {
        box.appendChild(buildSeriesCard(series, league));
      }
    }
  }
}

function buildSeriesCard(series, league) {
  const card = document.createElement("div");
  card.className = "series-card";

  const teamRow = (team) => {
    const isWinner = series.winner_id && series.winner_id === team.id;
    return `
      <div class="series-team${isWinner ? " winner" : ""}">
        <span class="series-seed">${esc(team.seed)}</span>
        <img class="series-logo" src="${safeUrl(team.logo_url)}" alt="">
        <span class="series-name">${esc(team.short_name || team.name)}</span>
        <span class="series-wins">${esc(team.wins)}</span>
      </div>`;
  };

  const played = series.games.length;
  const note = series.completed
    ? "серия завершена"
    : (played ? `сыграно матчей: ${played}` : "серия ещё не началась");

  card.innerHTML = `
    <div class="series-teams">
      ${teamRow(series.team_a)}
      ${teamRow(series.team_b)}
    </div>
    <div class="series-foot">
      <span class="series-note">${esc(note)}</span>
      <span class="series-toggle">Матчи ▾</span>
    </div>
    <div class="series-games hidden"></div>
  `;

  const gamesBox = card.querySelector(".series-games");
  const toggleLabel = card.querySelector(".series-toggle");

  card.querySelector(".series-foot").addEventListener("click", () => {
    const nowHidden = gamesBox.classList.toggle("hidden");
    toggleLabel.textContent = nowHidden ? "Матчи ▾" : "Матчи ▴";

    // список матчей строим один раз, при первом раскрытии
    if (!nowHidden && !gamesBox.dataset.filled) {
      series.games.forEach((game, i) => {
        const finished = game.status === "final";
        const score = (game.score_a != null && game.score_b != null)
          ? `${game.score_a} : ${game.score_b}` : "—";

        const row = document.createElement("div");
        row.className = "series-game" + (finished ? " clickable" : "");
        row.innerHTML = `
          <span class="sg-num">Матч ${i + 1}</span>
          <span class="sg-date">${esc(formatShortDate(game.date))}</span>
          <span class="sg-score">${esc(score)}</span>`;
        if (finished) {
          row.addEventListener("click", () => showBoxScore(game, league, "standings"));
        }
        gamesBox.appendChild(row);
      });
      gamesBox.dataset.filled = "1";
    }
  });

  return card;
}

// ===== Вкладка «Матчи»: результаты и календарь =====
function showGames(league) {
  const content = document.getElementById("tab-content");
  content.className = "";
  content.innerHTML = `
    <div class="subtabs">
      <button class="subtab" data-sub="results">Результаты</button>
      <button class="subtab" data-sub="schedule">Календарь</button>
      <button class="subtab subtab-narrow" data-sub="date" title="Выбрать дату">📅</button>
    </div>
    <div id="date-bar" class="date-bar hidden">
      <button class="date-nav" id="prev-day">‹</button>
      <input type="date" id="date-input" value="${gamesDate}">
      <button class="date-nav" id="next-day">›</button>
    </div>
    <div id="games-list" class="muted">Загрузка…</div>
  `;

  const subtabs = content.querySelectorAll(".subtab");
  subtabs.forEach(btn => {
    if (btn.dataset.sub === gamesSubTab) btn.classList.add("active");
    btn.addEventListener("click", () => {
      gamesSubTab = btn.dataset.sub;
      subtabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      loadGames(league, true);
    });
  });

  // панель дат: стрелки на день назад/вперёд и сам выбор дня
  document.getElementById("prev-day").addEventListener("click", () => {
    gamesDate = addDays(gamesDate, -1);
    loadGamesByDate(league);
  });
  document.getElementById("next-day").addEventListener("click", () => {
    gamesDate = addDays(gamesDate, 1);
    loadGamesByDate(league);
  });
  document.getElementById("date-input").addEventListener("change", (e) => {
    gamesDate = e.target.value;
    loadGamesByDate(league);
  });

  loadGames(league, true);
}

// Режим «Дата»: матчи одного выбранного дня.
async function loadGamesByDate(league) {
  const box = document.getElementById("games-list");
  document.getElementById("date-input").value = gamesDate;
  box.className = "muted";
  box.textContent = "Загрузка…";

  try {
    const games = await api(`/api/leagues/${league.id}/games?date=${gamesDate}`);
    if (!games || games.length === 0) {
      box.className = "muted";
      box.textContent = "На эту дату матчей нет.";
      return;
    }
    box.className = "";
    box.innerHTML = "";
    box.dataset.lastDate = "";
    appendGames(games, league, box);
  } catch (e) {
    box.className = "muted";
    box.textContent = "Не удалось загрузить матчи 😕";
  }
}

// reset=true — начинаем список заново, reset=false — дописываем следующую страницу
async function loadGames(league, reset) {
  const box = document.getElementById("games-list");
  const dateBar = document.getElementById("date-bar");

  // Выбор даты показываем только в своём режиме, списки — в остальных.
  if (gamesSubTab === "date") {
    dateBar.classList.remove("hidden");
    loadGamesByDate(league);
    return;
  }
  dateBar.classList.add("hidden");

  if (reset) {
    gamesOffset = 0;
    box.className = "muted";
    box.textContent = "Загрузка…";
    box.dataset.lastDate = "";
  }

  try {
    const url = `/api/leagues/${league.id}/games/list`
      + `?mode=${gamesSubTab}&limit=${GAMES_PAGE}&offset=${gamesOffset}`;
    const result = await api(url);
    const games = (result && result.games) || [];

    if (reset) {
      if (games.length === 0) {
        box.className = "muted";
        box.textContent = gamesSubTab === "schedule"
          ? "Межсезонье — ближайших матчей пока нет. Загляни в «Результаты»."
          : "Сыгранных матчей пока нет.";
        return;
      }
      box.className = "";
      box.innerHTML = "";
    }

    // старую кнопку «Показать ещё» убираем — вместо неё придёт новая
    const oldMore = box.querySelector(".load-more");
    if (oldMore) oldMore.remove();

    appendGames(games, league, box);
    gamesOffset += games.length;

    if (result.has_more) {
      const more = document.createElement("button");
      more.className = "load-more";
      more.textContent = "Показать ещё";
      more.addEventListener("click", () => {
        more.disabled = true;
        more.textContent = "Загрузка…";
        loadGames(league, false);
      });
      box.appendChild(more);
    }
  } catch (e) {
    if (reset) {
      box.className = "muted";
      box.textContent = "Не удалось загрузить матчи 😕";
    }
  }
}

function appendGames(games, league, box) {
  // В ВТБ привычен порядок «хозяева — гости» (хозяева сверху),
  // в NBA — американский «гости — хозяева». Каждой лиге — свой вид.
  const homeFirst = league.id === "vtb";

  for (const g of games) {
    // Заголовок дня ставим, когда дата сменилась. Последнюю дату держим
    // на самом контейнере, чтобы она пережила подгрузку следующей страницы.
    if (g.game_date !== box.dataset.lastDate) {
      box.dataset.lastDate = g.game_date;
      const day = document.createElement("div");
      day.className = "day-title";
      day.textContent = formatDayTitle(g.game_date);
      box.appendChild(day);
    }
    box.appendChild(buildGameCard(g, league, homeFirst));
  }
}

function buildGameCard(g, league, homeFirst) {
  const finished = g.status === "final";
  const live = g.status === "live";
  const statusText = finished ? "Финал" : (live ? "LIVE" : formatTime(g.datetime));
  const showScore = finished || live;

  // У матчей плей-офф и предсезонки показываем стадию, у регулярки — тур.
  const stageLine = (g.stage && g.stage !== "regular" && g.round_label)
    ? `<div class="game-stage">${esc(g.round_label)}</div>` : "";

  const awayRow = `
    <div class="game-team">
      <img class="game-logo" src="${safeUrl(g.away_logo)}" alt="">
      <span class="game-tname">${esc(g.away_short || g.away_name)}</span>
      <span class="game-score">${showScore ? esc(g.away_score) : ""}</span>
    </div>`;
  const homeRow = `
    <div class="game-team">
      <img class="game-logo" src="${safeUrl(g.home_logo)}" alt="">
      <span class="game-tname">${esc(g.home_short || g.home_name)}</span>
      <span class="game-score">${showScore ? esc(g.home_score) : ""}</span>
    </div>`;

  const card = document.createElement("div");
  card.className = "game-card" + (showScore ? " clickable" : "");
  card.innerHTML = `
    ${stageLine}
    <div class="game-status ${live ? "live" : ""}">${esc(statusText)}</div>
    ${homeFirst ? homeRow + awayRow : awayRow + homeRow}`;
  if (showScore) card.addEventListener("click", () => showBoxScore(g, league, "games"));
  return card;
}

// ===== Вкладка «Новости» =====
// Показываем ровно то, что пришло в ленте: заголовок, аннотацию источника,
// его название и ссылку на оригинал. Полные тексты к себе не тянем —
// этого требуют условия использования лент (в частности, у ESPN).
async function showNews(league) {
  const content = document.getElementById("tab-content");
  content.className = "";
  content.innerHTML = `<div id="news-list" class="muted">Загрузка…</div>`;
  loadNews(league, true);
}

async function loadNews(league, reset) {
  const box = document.getElementById("news-list");

  if (reset) {
    newsOffset = 0;
    box.className = "muted";
    box.textContent = "Загрузка…";
  }

  try {
    const result = await api(
      `/api/leagues/${league.id}/news?limit=${NEWS_PAGE}&offset=${newsOffset}`
    );
    const items = (result && result.news) || [];

    if (reset) {
      if (items.length === 0) {
        box.className = "muted";
        box.textContent = "Новостей пока нет.";
        return;
      }
      box.className = "";
      box.innerHTML = "";
    }

    const oldMore = box.querySelector(".load-more");
    if (oldMore) oldMore.remove();

    for (const item of items) box.appendChild(buildNewsCard(item));
    newsOffset += items.length;

    if (result.has_more) {
      const more = document.createElement("button");
      more.className = "load-more";
      more.textContent = "Показать ещё";
      more.addEventListener("click", () => {
        more.disabled = true;
        more.textContent = "Загрузка…";
        loadNews(league, false);
      });
      box.appendChild(more);
    }
  } catch (e) {
    if (reset) {
      box.className = "muted";
      box.textContent = "Не удалось загрузить новости 😕";
    }
  }
}

function buildNewsCard(item) {
  const card = document.createElement("a");
  card.className = "news-card";
  card.href = safeUrl(item.link);
  card.target = "_blank";
  card.rel = "noopener noreferrer";

  const image = item.image_url
    ? `<img class="news-image" src="${safeUrl(item.image_url)}" alt="" loading="lazy">` : "";
  const summary = item.summary
    ? `<div class="news-summary">${esc(item.summary)}</div>` : "";

  card.innerHTML = `
    ${image}
    <div class="news-body">
      <div class="news-title">${esc(item.title)}</div>
      ${summary}
      <div class="news-meta">
        <span class="news-source">${esc(item.source)}</span>
        <span class="news-date">${esc(formatNewsDate(item.published))}</span>
      </div>
    </div>`;
  return card;
}

function formatNewsDate(iso) {
  if (!iso) return "";
  const day = iso.slice(0, 10);
  const today = todayStr();
  if (day === today) return `сегодня, ${iso.slice(11, 16)}`;
  if (day === addDays(today, -1)) return "вчера";
  return `${Number(iso.slice(8, 10))} ${MONTHS_RU[Number(iso.slice(5, 7)) - 1]}`;
}

// ===== Экран матча: box score =====
// returnTab — на какую вкладку лиги вернуться по кнопке «Назад»
// (мы попадаем сюда и из списка матчей, и из сетки плей-офф).
async function showBoxScore(game, league, returnTab = "games") {
  pushHistory(() => showLeague(league, returnTab));
  const backLabel = returnTab === "standings" ? "‹ Плей-офф" : "‹ Матчи";
  root.innerHTML = `
    <header class="app-header"><button class="back" id="back">${backLabel}</button></header>
    <main class="container"><div id="box" class="muted">Загрузка…</div></main>
  `;
  document.getElementById("back").addEventListener("click", goBack);

  try {
    renderBoxScore(await api(`/api/games/${game.id}/boxscore`), league);
  } catch (e) {
    document.getElementById("box").textContent = "Не удалось загрузить статистику матча 😕";
  }
}

function renderBoxScore(box, league) {
  const el = document.getElementById("box");
  if (!box || !box.teams || box.teams.length < 2) {
    el.className = "muted";
    el.textContent = "Статистика матча недоступна.";
    return;
  }
  boxActiveTeam = 0;
  el.className = "";

  // хозяев/гостей находим по пометке; порядок показа зависит от лиги
  // (ВТБ — хозяева сверху, NBA/Евролига — гости сверху)
  const home = box.teams.find(t => t.home_away === "home") || box.teams[1];
  const away = box.teams.find(t => t.home_away === "away") || box.teams[0];
  const homeFirst = league && league.id === "vtb";
  const ordered = homeFirst ? [home, away] : [away, home];

  const numQ = Math.max(ordered[0].quarters.length, ordered[1].quarters.length);
  const qHeaders = [];
  for (let i = 0; i < numQ; i++) qHeaders.push(i < 4 ? String(i + 1) : "ОТ");

  const qRow = (t) => `
    <div class="ls-row">
      <span class="ls-team"><img class="ls-logo" src="${safeUrl(t.logo)}" alt="">${esc(t.short_name)}</span>
      ${t.quarters.map(q => `<span class="ls-q">${esc(q)}</span>`).join("")}
      <span class="ls-total">${esc(t.score)}</span>
    </div>`;

  el.innerHTML = `
    <div class="linescore">
      <div class="ls-row ls-head">
        <span class="ls-team"></span>
        ${qHeaders.map(h => `<span class="ls-q">${esc(h)}</span>`).join("")}
        <span class="ls-total">И</span>
      </div>
      ${qRow(ordered[0])}
      ${qRow(ordered[1])}
    </div>
    <div class="box-tabs">
      <button class="box-tab" data-i="0">${esc(ordered[0].short_name || "1")}</button>
      <button class="box-tab" data-i="1">${esc(ordered[1].short_name || "2")}</button>
    </div>
    <div id="box-team"></div>
  `;

  const tabs = el.querySelectorAll(".box-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      boxActiveTeam = Number(tab.dataset.i);
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      renderBoxTeam(ordered[boxActiveTeam]);
    });
  });
  tabs[boxActiveTeam].classList.add("active");
  renderBoxTeam(ordered[boxActiveTeam]);
}

function renderBoxTeam(team) {
  const box = document.getElementById("box-team");
  const t = team.totals || {};

  const totals = `
    <div class="team-totals">
      <div class="tt-item"><span class="tt-val">${esc(t.fg || "—")}</span><span class="tt-lbl">FG ${t.fg_pct ? esc(t.fg_pct) + "%" : ""}</span></div>
      <div class="tt-item"><span class="tt-val">${esc(t.fg3 || "—")}</span><span class="tt-lbl">3PT ${t.fg3_pct ? esc(t.fg3_pct) + "%" : ""}</span></div>
      <div class="tt-item"><span class="tt-val">${esc(t.ft || "—")}</span><span class="tt-lbl">FT ${t.ft_pct ? esc(t.ft_pct) + "%" : ""}</span></div>
      <div class="tt-item"><span class="tt-val">${esc(t.reb || "—")}</span><span class="tt-lbl">Подборы</span></div>
      <div class="tt-item"><span class="tt-val">${esc(t.ast || "—")}</span><span class="tt-lbl">Передачи</span></div>
      <div class="tt-item"><span class="tt-val">${esc(t.to || "—")}</span><span class="tt-lbl">Потери</span></div>
    </div>`;

  const head = `
    <div class="bs-row bs-head">
      <span class="bs-name">Игрок</span>
      <span>МИН</span><span>ОЧ</span><span>ПД</span><span>ПАС</span>
      <span>ПХ</span><span>БЛ</span><span>ПТ</span>
      <span class="bs-wide">FG</span><span class="bs-wide">3PT</span><span class="bs-wide">FT</span><span>+/-</span>
    </div>`;

  const rows = (team.players || []).map(p => `
    <div class="bs-row">
      <span class="bs-name">${p.starter ? "<span class='starter'>•</span> " : ""}${esc(p.name)}</span>
      <span>${esc(p.min)}</span><span class="bs-pts">${esc(p.pts)}</span><span>${esc(p.reb)}</span><span>${esc(p.ast)}</span>
      <span>${esc(p.stl)}</span><span>${esc(p.blk)}</span><span>${esc(p.to)}</span>
      <span class="bs-wide">${esc(p.fg)}</span><span class="bs-wide">${esc(p.fg3)}</span><span class="bs-wide">${esc(p.ft)}</span><span>${esc(p.plus_minus)}</span>
    </div>`).join("");

  box.innerHTML = totals + `<div class="bs-scroll"><div class="bs-table">${head}${rows}</div></div>`;
}

// ===== Вкладка «Команды» =====
function renderTeams(teams, league) {
  const content = document.getElementById("tab-content");
  if (!teams || teams.length === 0) {
    content.className = "muted";
    content.textContent = "Команд пока нет.";
    return;
  }
  content.className = "";
  content.innerHTML = "";

  const grid = document.createElement("div");
  grid.className = "team-grid";
  for (const team of teams) {
    const card = document.createElement("div");
    card.className = "team-card";
    card.innerHTML = `<img class="team-logo" src="${safeUrl(team.logo_url)}" alt=""><div class="team-name">${esc(team.name)}</div>`;
    card.addEventListener("click", () => showTeam(team, league));
    // звезда команды в правом верхнем углу карточки
    if (favEnabled) {
      const star = makeStar("team", team.id, league.id);
      star.classList.add("star-corner");
      card.appendChild(star);
    }
    grid.appendChild(card);
  }
  content.appendChild(grid);
}

// ===== Экран команды: состав =====
async function showTeam(team, league) {
  pushHistory(() => showLeague(league, "teams"));
  root.innerHTML = `
    <header class="app-header">
      <button class="back" id="back">‹ ${esc(league.name)}</button>
      <div class="team-head"><img class="team-head-logo" src="${safeUrl(team.logo_url)}" alt=""><h1>${esc(team.name)}</h1></div>
    </header>
    <main class="container"><div id="roster" class="muted">Загрузка…</div></main>
  `;
  document.getElementById("back").addEventListener("click", goBack);

  try {
    renderRoster(await api(`/api/teams/${team.id}/roster`), team, league);
  } catch (e) {
    document.getElementById("roster").textContent = "Не удалось загрузить состав 😕";
  }
}

function renderRoster(players, team, league) {
  const box = document.getElementById("roster");
  if (!players || players.length === 0) {
    box.className = "muted";
    box.textContent = "Состав пока не загружен.";
    return;
  }
  box.className = "";
  box.innerHTML = "";

  const list = document.createElement("div");
  list.className = "player-list";
  for (const p of players) {
    const item = document.createElement("div");
    item.className = "player-item";
    item.innerHTML = `
      ${avatarHtml(p, "player-photo")}
      <div class="player-info">
        <div class="player-name">${esc(p.name)}</div>
        <div class="player-meta">${esc(p.position)}${p.number ? " · #" + esc(p.number) : ""}</div>
      </div>
      <div class="arrow">›</div>`;
    item.addEventListener("click", () => showPlayer(p, team, league));
    list.appendChild(item);
  }
  box.appendChild(list);
}

// ===== Экран игрока: статистика за сезон =====
async function showPlayer(player, team, league, backFn) {
  // куда вести кнопкой «Назад»: из состава — в команду, из избранного —
  // в избранное (там нет настоящей команды, и showTeam сломалась бы)
  pushHistory(backFn || (() => showTeam(team, league)));
  root.innerHTML = `
    <header class="app-header"><button class="back" id="back">‹ ${esc(team.name)}</button></header>
    <main class="container">
      <div class="player-card">
        ${avatarHtml(player, "player-card-photo")}
        <div class="player-card-name">${esc(player.name)}</div>
        <div class="player-card-sub">${esc(player.position)}${player.number ? " · #" + esc(player.number) : ""}${player.height ? " · " + esc(player.height) : ""}</div>
        <div id="player-star"></div>
      </div>
      <div id="stats" class="muted">Загрузка статистики…</div>
    </main>
  `;
  document.getElementById("back").addEventListener("click", goBack);

  // кнопка «в избранное» под именем игрока (текстом, крупнее звезды)
  if (favEnabled) {
    const holder = document.getElementById("player-star");
    const btn = document.createElement("button");
    const setLook = (on) => {
      btn.className = "fav-button" + (on ? " on" : "");
      btn.textContent = on ? "★ В избранном" : "☆ В избранное";
    };
    setLook(isFav("player", player.id));
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const nowFav = await toggleFav("player", player.id, league.id,
        { label: player.name, photo: player.photo_url });
      setLook(nowFav);
      btn.disabled = false;
    });
    holder.appendChild(btn);
  }

  try {
    renderStats(await api(`/api/players/${player.id}/stats`));
  } catch (e) {
    document.getElementById("stats").textContent = "Не удалось загрузить статистику 😕";
  }
}

function renderStats(stats) {
  const box = document.getElementById("stats");
  if (!stats) {
    box.className = "muted";
    box.textContent = "Статистики за сезон нет.";
    return;
  }
  box.className = "";
  box.innerHTML = "";

  const main = [
    { label: "Очки", value: stats.pts },
    { label: "Подборы", value: stats.reb },
    { label: "Передачи", value: stats.ast },
  ];
  const mainGrid = document.createElement("div");
  mainGrid.className = "stat-main";
  for (const s of main) {
    const cell = document.createElement("div");
    cell.className = "stat-box big";
    cell.innerHTML = `<div class="stat-value">${esc(s.value ?? "—")}</div><div class="stat-label">${esc(s.label)}</div>`;
    mainGrid.appendChild(cell);
  }
  box.appendChild(mainGrid);

  const more = [
    { label: "Игры", value: stats.games_played }, { label: "Минуты", value: stats.minutes },
    { label: "Перехваты", value: stats.stl }, { label: "Блоки", value: stats.blk },
    { label: "Потери", value: stats.tov }, { label: "FG %", value: stats.fg_pct },
    { label: "3P %", value: stats.fg3_pct }, { label: "FT %", value: stats.ft_pct },
  ];
  const moreGrid = document.createElement("div");
  moreGrid.className = "stat-more";
  for (const s of more) {
    const cell = document.createElement("div");
    cell.className = "stat-box";
    cell.innerHTML = `<div class="stat-value">${esc(s.value ?? "—")}</div><div class="stat-label">${esc(s.label)}</div>`;
    moreGrid.appendChild(cell);
  }
  box.appendChild(moreGrid);
}

// ===== Экран избранного =====
// Три раздела: Лиги / Команды / Игроки. У команд — настройка моментов
// уведомлений. Данные о лигах и командах берём из тех же эндпоинтов, что и
// весь остальной интерфейс, а список подписок — из /api/favorites.

let favActiveTab = "team";           // какой раздел открыт: team | league | player

const FAV_TABS = [
  { key: "team", label: "Команды" },
  { key: "league", label: "Лиги" },
  { key: "player", label: "Игроки" },
];

// Моменты уведомлений команды — подписи и порядок.
const NOTIFY_MOMENTS = [
  { key: "hour", label: "За час" },
  { key: "min30", label: "За 30 мин" },
  { key: "min10", label: "За 10 мин" },
  { key: "start", label: "Старт матча" },
  { key: "final", label: "Финальный счёт" },
];

async function showFavorites() {
  root.innerHTML = `
    <header class="app-header">
      <button class="back" id="back">‹ Назад</button>
      <h1>⭐ Избранное</h1>
    </header>
    <nav class="tabs" id="fav-tabs"></nav>
    <main class="container"><div id="fav-content" class="muted">Загрузка…</div></main>
  `;
  document.getElementById("back").addEventListener("click", goBack);

  const tabsBox = document.getElementById("fav-tabs");
  FAV_TABS.forEach(t => {
    const btn = document.createElement("button");
    btn.className = "tab" + (t.key === favActiveTab ? " active" : "");
    btn.textContent = t.label;
    btn.addEventListener("click", () => {
      favActiveTab = t.key;
      tabsBox.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderFavList();
    });
    tabsBox.appendChild(btn);
  });

  await renderFavList();
}

// Кеш справочников, чтобы по избранному показать имена и логотипы. Лиги и
// команды тянем один раз за сессию.
let _leaguesCache = null;
const _teamsCache = {};           // league_id -> [teams]

async function getLeaguesMap() {
  if (!_leaguesCache) {
    const data = await api("/api/leagues");
    _leaguesCache = {};
    for (const l of data) _leaguesCache[l.id] = l;
  }
  return _leaguesCache;
}

async function getTeamsMap(leagueId) {
  if (!_teamsCache[leagueId]) {
    const data = await api(`/api/leagues/${leagueId}/teams`);
    const map = {};
    for (const t of data) map[t.id] = t;
    _teamsCache[leagueId] = map;
  }
  return _teamsCache[leagueId];
}

async function renderFavList() {
  const box = document.getElementById("fav-content");
  box.className = "muted";
  box.textContent = "Загрузка…";

  let favorites;
  try {
    const data = await favApi("GET", "/api/favorites");
    favorites = (data && data.data) || [];
  } catch (e) {
    box.className = "muted";
    box.textContent = "Не удалось загрузить избранное 😕";
    return;
  }

  const items = favorites.filter(f => f.kind === favActiveTab);
  if (items.length === 0) {
    box.className = "muted";
    box.textContent = emptyText(favActiveTab);
    return;
  }
  box.className = "";
  box.innerHTML = "";

  if (favActiveTab === "league") await renderFavLeagues(items, box);
  else if (favActiveTab === "team") await renderFavTeams(items, box);
  else await renderFavPlayers(items, box);
}

function emptyText(kind) {
  if (kind === "league") return "Нет избранных лиг. Добавь их звёздочкой на главной.";
  if (kind === "team") return "Нет избранных команд. Добавь их звёздочкой в списке команд лиги.";
  return "Нет избранных игроков. Добавь их на карточке игрока.";
}

// --- Раздел «Лиги» ---
async function renderFavLeagues(items, box) {
  const leagues = await getLeaguesMap();
  for (const fav of items) {
    const league = leagues[fav.entity_id] || { id: fav.entity_id, name: fav.entity_id };
    const row = document.createElement("div");
    row.className = "fav-row";
    row.innerHTML = `<div class="fav-main"><div class="fav-name">${esc(league.name)}</div>
      <div class="fav-sub">Уведомления за 15 минут до матчей лиги</div></div>`;
    row.addEventListener("click", () => { pushHistory(showFavorites); showLeague(league); });
    row.appendChild(makeRemoveButton("league", fav.entity_id));
    box.appendChild(row);
  }
}

// --- Раздел «Команды» с настройкой уведомлений ---
async function renderFavTeams(items, box) {
  const leagues = await getLeaguesMap();
  for (const fav of items) {
    const teams = await getTeamsMap(fav.league_id);
    const team = teams[fav.entity_id] || { id: fav.entity_id, name: fav.entity_id };
    const league = leagues[fav.league_id];

    const row = document.createElement("div");
    row.className = "fav-card";

    const head = document.createElement("div");
    head.className = "fav-row";
    head.innerHTML = `
      <img class="fav-logo" src="${safeUrl(team.logo_url)}" alt="">
      <div class="fav-main">
        <div class="fav-name">${esc(team.name)}</div>
        <div class="fav-sub">${esc(league ? league.name : "")}</div>
      </div>`;
    head.appendChild(makeRemoveButton("team", fav.entity_id));
    row.appendChild(head);

    // настройка моментов уведомлений
    const prefs = fav.prefs || {};
    const grid = document.createElement("div");
    grid.className = "notify-grid";
    NOTIFY_MOMENTS.forEach(m => {
      const chip = document.createElement("button");
      chip.className = "notify-chip" + (prefs[m.key] ? " on" : "");
      chip.textContent = m.label;
      chip.addEventListener("click", async () => {
        const next = !chip.classList.contains("on");
        chip.classList.toggle("on", next);
        prefs[m.key] = next;
        try {
          await favApi("POST", "/api/favorites/team-prefs",
            { entity_id: fav.entity_id, prefs });
          if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
        } catch (e) {
          chip.classList.toggle("on", !next);   // откат при ошибке
          prefs[m.key] = !next;
        }
      });
      grid.appendChild(chip);
    });
    row.appendChild(grid);
    box.appendChild(row);
  }
}

// --- Раздел «Игроки» ---
async function renderFavPlayers(items, box) {
  const leagues = await getLeaguesMap();
  for (const fav of items) {
    // Имя и фото сохранены в момент добавления (в карточке игрока они есть),
    // поэтому лишних запросов не делаем. Если подписи почему-то нет (старая
    // запись до этого обновления) — показываем «Игрок» вместо кода.
    const name = fav.label || "Игрок";
    const photo = fav.photo || null;
    const league = leagues[fav.league_id];

    const row = document.createElement("div");
    row.className = "fav-row";
    const avatar = photo
      ? `<img class="fav-logo round" src="${safeUrl(photo)}" alt="">`
      : `<div class="fav-logo round avatar-fallback">${esc(initials(name))}</div>`;
    row.innerHTML = `${avatar}
      <div class="fav-main">
        <div class="fav-name">${esc(name)}</div>
        <div class="fav-sub">${esc(league ? league.name : "")} · статистика после матчей</div>
      </div>`;

    // Открываем карточку игрока. Команда игрока нам тут неизвестна (мы её не
    // храним), но showPlayer нужна команда для кнопки «назад» и запроса
    // статистики. Передаём минимально необходимое: id игрока и лигу.
    // Заголовок «назад» просто вернёт в избранное.
    row.addEventListener("click", () => {
      if (!league) return;
      const stubTeam = { id: null, name: "Избранное" };
      showPlayer({ id: fav.entity_id, name, photo_url: photo }, stubTeam, league,
                 showFavorites);
    });
    row.appendChild(makeRemoveButton("player", fav.entity_id));
    box.appendChild(row);
  }
}

// Кнопка удаления из избранного (крестик справа в строке).
function makeRemoveButton(kind, entityId) {
  const btn = document.createElement("button");
  btn.className = "fav-remove";
  btn.textContent = "✕";
  btn.setAttribute("aria-label", "Убрать из избранного");
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    btn.disabled = true;
    await toggleFav(kind, entityId);
    renderFavList();               // перерисуём список без удалённого
  });
  return btn;
}

// старт приложения
initTelegram();
loadFavorites().finally(showHome);