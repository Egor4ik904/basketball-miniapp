# app/brackets.py
# Сборка сетки плей-офф из матчей.
#
# Сетку мы нигде не храним: она целиком выводится из таблицы games. У всех матчей
# одной серии одинаковый series_key (его проставляет app/stages.py), поэтому
# достаточно сгруппировать матчи по этому ключу и посчитать победы. Отдельной
# таблицы «серии» нет сознательно — иначе появилась бы вторая версия правды,
# которую пришлось бы синхронизировать с матчами.


def _int(value):
    """Счёт в базе лежит строкой, а сравнивать надо числа."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _new_series(row: dict) -> dict:
    """Заготовка серии по её первому матчу.

    Порядок команд задаёт первая игра: в плей-офф её принимает команда с лучшим
    посевом, поэтому она и оказывается слева — как в привычных сетках.
    """
    # Конференцию ставим, только если обе команды из одной. В финале лиги
    # соперники из разных конференций — там она остаётся пустой, и такая
    # серия правильно не попадает ни в блок «Восток», ни в «Запад».
    home_conf, away_conf = row["home_conf"], row["away_conf"]
    conference = home_conf if home_conf and home_conf == away_conf else None

    return {
        "series_key": row["series_key"],
        "label": row["stage_label"],
        "round": row["series_round"],
        "stage": row["stage"],
        "conference": conference,
        "team_a": {
            "id": row["home_team_id"],
            "name": row["home_name"],
            "short_name": row["home_short"],
            "logo_url": row["home_logo"],
            "seed": row["home_seed"],
            "wins": 0,
        },
        "team_b": {
            "id": row["away_team_id"],
            "name": row["away_name"],
            "short_name": row["away_short"],
            "logo_url": row["away_logo"],
            "seed": row["away_seed"],
            "wins": 0,
        },
        "games": [],
    }


def build_bracket(rows: list[dict]) -> list[dict]:
    """Принимает результат db.get_playoff_games(), отдаёт список кругов:

    [
      {"round": 1, "label": "1/4 финала", "series": [ ... ]},
      {"round": 2, "label": "1/2 финала", "series": [ ... ]},
      ...
    ]

    Круги идут от раннего к позднему — это порядок колонок в сетке слева направо.
    """
    series_map: dict[str, dict] = {}

    for row in rows:
        key = row["series_key"]
        series = series_map.get(key)
        if series is None:
            series = _new_series(row)
            series_map[key] = series

        home_score = _int(row["home_score"])
        away_score = _int(row["away_score"])

        # Хозяин поля меняется от игры к игре, поэтому счёт приводим
        # к постоянному порядку «team_a — team_b».
        if row["home_team_id"] == series["team_a"]["id"]:
            score_a, score_b = home_score, away_score
        else:
            score_a, score_b = away_score, home_score

        finished = (
            row["status"] == "final"
            and score_a is not None
            and score_b is not None
        )
        if finished:
            if score_a > score_b:
                series["team_a"]["wins"] += 1
            elif score_b > score_a:
                series["team_b"]["wins"] += 1

        series["games"].append({
            "id": row["id"],
            "date": row["game_date"],
            "datetime": row["datetime"],
            "status": row["status"],
            "score_a": score_a,
            "score_b": score_b,
            "home_team_id": row["home_team_id"],
        })

    # Итоги каждой серии
    for series in series_map.values():
        series["games"].sort(key=lambda g: g["datetime"] or "")

        # Источники не выкладывают несыгранные игры серии (при 4:1 матчей будет
        # ровно пять), поэтому «все игры завершены» и означает «серия закончена».
        completed = bool(series["games"]) and all(
            g["status"] == "final" for g in series["games"]
        )
        series["completed"] = completed

        wins_a = series["team_a"]["wins"]
        wins_b = series["team_b"]["wins"]
        if completed and wins_a != wins_b:
            series["winner_id"] = (
                series["team_a"]["id"] if wins_a > wins_b else series["team_b"]["id"]
            )
        else:
            series["winner_id"] = None

    def best_seed(series: dict) -> int:
        """Лучшее (наименьшее) место из двух команд серии. Нужно, чтобы внутри
        круга пары шли сверху вниз от сильнейшей — как в привычной сетке."""
        seeds = [s for s in (series["team_a"]["seed"], series["team_b"]["seed"])
                 if isinstance(s, int)]
        return min(seeds) if seeds else 99

    # Раскладываем по кругам. Круг None (стадию не удалось опознать) — в конец.
    ordered = sorted(
        series_map.values(),
        key=lambda s: (
            99 if s["round"] is None else s["round"],
            s["conference"] or "",
            best_seed(s),
            s["series_key"],
        ),
    )

    rounds: list[dict] = []
    for series in ordered:
        if not rounds or rounds[-1]["round"] != series["round"]:
            label = "Плей-ин" if series["stage"] == "playin" else series["label"]
            rounds.append({"round": series["round"], "label": label, "series": []})
        rounds[-1]["series"].append(series)

    return rounds