# app/stages.py
# Единая модель стадий турнира для всех трёх лиг.
#
# Каждая лига называет стадии по-своему: у Евролиги это коды RS/PI/PO/FF,
# у ВТБ — русский текст «1/4 финала (2)», у NBA — числовой season.type плюс
# заголовок вроде «NBA Finals - Game 5». Этот модуль — единственное место,
# где живут эти различия. Наружу все три отдают одинаковый набор полей:
#
#   stage        — код стадии: regular / playin / playoff
#   stage_label  — как показать человеку: «Регулярный чемпионат», «1/4 финала»
#   series_key   — идентификатор серии: у всех матчей одной серии одинаковый,
#                  у регулярки — None. Именно по нему собирается сетка.
#   series_round — номер круга: 1 — самый ранний (1/4 финала или 1-й раунд),
#                  дальше 2, 3, 4. Это номер колонки в сетке слева направо.
#   round_label  — «Тур 17» для регулярки, название стадии для плей-офф.
#
# Добавляя четвёртую лигу, пишешь сюда одну функцию — остальной код не трогаешь.

PRESEASON = "preseason"
REGULAR = "regular"
PLAYIN = "playin"
PLAYOFF = "playoff"


def _result(stage, stage_label, series_key=None, series_round=None, round_label=None):
    return {
        "stage": stage,
        "stage_label": stage_label,
        "series_key": series_key,
        "series_round": series_round,
        "round_label": round_label or stage_label,
    }


# ============================================================
# ЕВРОЛИГА
# ============================================================
# Проверено на сезоне E2025 (402 матча):
#   round='RS' 380 матчей, 'PO' 16, 'PI' 3, 'FF' 3
#   group='Regular Season' | 'PLAYOFF A'..'PLAYOFF D' | 'A','B','C' (плей-ин)
#         | 'SEMIFINAL A', 'SEMIFINAL B', 'CHAMPIONSHIP GAME'

_EL_FINAL_FOUR = {
    "SEMIFINAL A": ("Полуфинал", 2),
    "SEMIFINAL B": ("Полуфинал", 2),
    "CHAMPIONSHIP GAME": ("Финал", 3),
    "THIRD PLACE GAME": ("Матч за 3-е место", 3),
}


def euroleague(round_code, group, gameday=None):
    """round / group / gameday из XML-ответа /v1/results."""
    round_code = (round_code or "").strip().upper()
    group = (group or "").strip().upper()

    if round_code == "RS":
        return _result(
            REGULAR, "Регулярный чемпионат",
            round_label=f"Тур {gameday}" if gameday else "Регулярный чемпионат",
        )

    if round_code == "PI":
        return _result(PLAYIN, "Плей-ин", series_key=f"PI:{group}", series_round=0)

    if round_code == "PO":
        # PLAYOFF A..D — четыре четвертьфинальные серии
        return _result(PLAYOFF, "1/4 финала", series_key=f"PO:{group}", series_round=1)

    if round_code == "FF":
        label, depth = _EL_FINAL_FOUR.get(group, ("Финал четырёх", 2))
        return _result(PLAYOFF, label, series_key=f"FF:{group}", series_round=depth)

    # неизвестный код — не теряем матч, просто не относим к плей-офф
    return _result(REGULAR, "Регулярный чемпионат")


# ============================================================
# ЕДИНАЯ ЛИГА ВТБ
# ============================================================
# Проверено на сезоне 2025/26 (254 матча). Поле CompNameRu:
#   'Регулярный чемпионат' 220, '1/4 финала (1)'..'(4)', '1/2 финала (1)'..'(2)',
#   'Финал', 'Финал за 3 место'
# Название серии уникально само по себе — его и берём как series_key.


def vtb(comp_name):
    """CompNameRu из ответа /Widget/Calendar/{season_id}."""
    name = (comp_name or "").strip()
    low = name.lower()

    if not name or "регулярн" in low:
        return _result(REGULAR, "Регулярный чемпионат")

    # ВАЖЕН ПОРЯДОК: «Финал за 3 место» и «1/4 финала» тоже содержат «финал»,
    # поэтому общая проверка на «финал» стоит последней.
    if "3 место" in low or "за 3" in low:
        return _result(PLAYOFF, "Матч за 3-е место", series_key=name, series_round=3)
    if "1/4" in low:
        return _result(PLAYOFF, "1/4 финала", series_key=name, series_round=1)
    if "1/2" in low:
        return _result(PLAYOFF, "1/2 финала", series_key=name, series_round=2)
    if "финал" in low:
        return _result(PLAYOFF, "Финал", series_key=name, series_round=3)

    # что-то незнакомое (например, новый формат) — считаем плей-офф без круга
    return _result(PLAYOFF, name, series_key=name, series_round=None)


# ============================================================
# NBA
# ============================================================
# Проверено на сезоне 2025/26. season.type: 2 — регулярка, 3 — плей-офф,
# 5 — плей-ин (season.slug соответственно regular-season / post-season /
# play-in-season). Название круга — в competitions[0].notes[0].headline.

_NBA_SEASON_TYPE = {1: PRESEASON, 2: REGULAR, 3: PLAYOFF, 5: PLAYIN}


def nba(season_type, headline, home_team_id, away_team_id):
    """season.type, notes[0].headline и id обеих команд из ответа scoreboard."""
    try:
        season_type = int(season_type)
    except (TypeError, ValueError):
        season_type = 2

    stage = _NBA_SEASON_TYPE.get(season_type, REGULAR)
    if stage == PRESEASON:
        return _result(PRESEASON, "Предсезонные матчи")
    if stage == REGULAR:
        return _result(REGULAR, "Регулярный чемпионат")

    # Две команды за плей-офф встречаются максимум в одной серии, поэтому
    # пара их id — надёжный ключ серии (у ESPN своего id серии нет).
    pair = "-".join(sorted([str(home_team_id), str(away_team_id)]))

    if stage == PLAYIN:
        return _result(PLAYIN, "Плей-ин", series_key=f"PI:{pair}", series_round=0)

    # ВАЖЕН ПОРЯДОК. Финал конференции ESPN называет «East Finals» — слова
    # «Conference» там нет, поэтому проверку на финал НБА надо делать РАНЬШЕ
    # общей проверки на «final», иначе финал конференции попадёт в финал лиги.
    head = (headline or "").lower()
    if "round" in head and ("1st" in head or "first" in head):
        label, depth = "1-й раунд", 1
    elif "semifinal" in head:
        label, depth = "Полуфинал конференции", 2
    elif "nba final" in head:
        label, depth = "Финал НБА", 4
    elif "final" in head:
        label, depth = "Финал конференции", 3
    else:
        label, depth = "Плей-офф", None

    return _result(PLAYOFF, label, series_key=f"PO:{pair}", series_round=depth)