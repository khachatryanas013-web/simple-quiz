"""Randomized Telegram questions generated from the full HTML trainer catalog."""

import json
import random
import re
from pathlib import Path

from question_quality import deduplicate_questions


CATALOG_PATH = Path(__file__).with_name("training_catalog.json")
EXTERNAL_PATH = Path(__file__).with_name("external_questions.json")
CATALOG_SOURCE = {
    "source": "Simple Quiz trainer catalog",
    "source_url": "https://github.com/AmiryanVDS/simple-quiz",
    "license": "Project-authored trainer data",
    "checked_at": "2026-08-03",
}


def _catalog() -> dict[str, list[list[str]]]:
    with CATALOG_PATH.open(encoding="utf-8") as catalog_file:
        return json.load(catalog_file)


def _mcq(prompt: str, correct: str, explanation: str, pool: list[str], source_id: str = "catalog") -> dict:
    candidates = list(dict.fromkeys(value for value in pool if value != correct))
    if len(candidates) < 3:
        return {}
    options = random.sample(candidates, 3) + [correct]
    random.shuffle(options)
    return {
        "question": prompt,
        "options": options,
        "correct": options.index(correct),
        "explanation": explanation,
        "answer_verified": True,
        **CATALOG_SOURCE,
        "source_id": f"catalog:{source_id}",
    }


def _build_buckets(catalog: dict[str, list[list[str]]]) -> list[list[dict]]:
    buckets: list[list[dict]] = []

    football = catalog["football"]
    buckets.append(
        [
            _mcq(
                f"Какое прозвище связано с клубом {team}?",
                nickname,
                clue,
                [row[1] for row in football],
            )
            for team, nickname, clue in football
        ]
    )
    buckets.append(
        [
            _mcq(
                f"Какой клуб связан с прозвищем «{nickname}»?",
                team,
                clue,
                [row[0] for row in football],
            )
            for team, nickname, clue in football
        ]
    )

    groups = catalog["worldCup2026Groups"]
    buckets.append(
        [
            _mcq(
                f"Какие сборные входят в {group}?",
                teams,
                clue,
                [row[1] for row in groups],
            )
            for group, teams, clue in groups
        ]
    )

    awards = catalog["worldCup2026Awards"]
    buckets.append(
        [
            _mcq(
                f"Кто указан как обладатель награды «{award}»?",
                winner,
                clue,
                [row[1] for row in awards],
            )
            for award, winner, clue in awards
        ]
    )

    scorers = catalog["worldCup2026Scorers"]
    buckets.append(
        [
            _mcq(
                f"Кто занял позицию «{place}» в списке бомбардиров?",
                player,
                clue,
                [row[1] for row in scorers],
            )
            for place, player, clue in scorers
        ]
    )

    leagues = catalog["leagueCards"]
    buckets.append(
        [
            _mcq(
                f"Какой клуб обозначается кодом {code} в {league}?",
                team,
                f"{team} — команда лиги {league}, код {code}.",
                [row[1] for row in leagues],
            )
            for code, team, league in leagues
        ]
    )
    buckets.append(
        [
            _mcq(
                f"К какой лиге относится команда {team}?",
                league,
                f"{team} выступает в {league}.",
                [row[2] for row in leagues],
            )
            for code, team, league in leagues
        ]
    )

    campaigns = catalog["campaigns"]
    buckets.append(
        [
            _mcq(
                f"Какой бренд или проект связан с кампанией «{name}»?",
                brand,
                clue,
                [row[1] for row in campaigns],
            )
            for name, brand, clue in campaigns
        ]
    )

    names = catalog["nameBridges"]
    buckets.append(
        [
            _mcq(
                f"С какой фигурой, словом или областью связан мост «{person}»?",
                bridge,
                clue,
                [row[1] for row in names],
            )
            for person, bridge, clue in names
        ]
    )

    mythology = catalog["mythology"]
    buckets.append(
        [
            _mcq(
                f"Что обозначает образ «{figure}»?",
                description,
                f"Традиция: {tradition}.",
                [row[1] for row in mythology],
            )
            for figure, description, tradition in mythology
        ]
    )

    pop_culture = catalog["popCulture"]
    buckets.append(
        [
            _mcq(
                f"Кто или что связано с «{title}»?",
                creator,
                clue,
                [row[1] for row in pop_culture],
            )
            for title, creator, clue in pop_culture
        ]
    )
    return [[question for question in bucket if question] for bucket in buckets]


def _external_questions() -> list[dict]:
    if not EXTERNAL_PATH.exists():
        return []
    with EXTERNAL_PATH.open(encoding="utf-8") as questions_file:
        raw_questions = json.load(questions_file)
    questions, _ = deduplicate_questions(raw_questions)
    # Telegram-тренажёр публикует только русскоязычные формулировки. Имена
    # команд и спортсменов могут оставаться латиницей, но текст вопроса должен
    # содержать кириллицу; англоязычный снапшот OpenTDB пока не показываем.
    questions = [
        question for question in questions
        if len(re.findall(r"[А-Яа-яЁё]", question["question"])) >= 4
        and not question["question"].startswith(("Как завершился матч ", "какой счёт был в матче "))
    ]
    return questions


def build_training_questions(count: int = 12) -> list[dict]:
    """Return a fresh mixed set, preferring all major trainer sections."""
    buckets = _build_buckets(_catalog())
    external = _external_questions()
    if external:
        for source in sorted({question["source"] for question in external}):
            buckets.append([question for question in external if question["source"] == source])
    random.shuffle(buckets)
    questions: list[dict] = []
    for bucket in buckets:
        if bucket and len(questions) < count:
            questions.append(random.choice(bucket))

    remaining = [question for bucket in buckets for question in bucket if question not in questions]
    random.shuffle(remaining)
    questions.extend(remaining[: max(0, count - len(questions))])
    random.shuffle(questions)
    return questions[:count]
