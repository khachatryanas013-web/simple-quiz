#!/usr/bin/env python3
"""Import OpenTDB sports questions and openfootball 2026 facts.

The generated JSON is committed so the bot does not call third-party APIs at
runtime. Re-run this script when refreshing the checked dataset.
"""

import html
import json
import re
import ssl
import sys
import csv
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pdmb_bot" / "external_questions.json"
LOCAL_OPENTDB = None
LOCAL_OPENFOOTBALL = None
LOCAL_OPENFOOTBALL_1994 = None
LOCAL_FOOTBALL_DATASETS = None
LOCAL_CHAMPIONS_LEAGUE = None
LOCAL_BASE = None
CHECKED_AT = date.today().isoformat()
OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/worldcup/master/2026--canada-usa-mexico/cup.txt"
OPENFOOTBALL_1994_URL = "https://raw.githubusercontent.com/openfootball/worldcup/master/1994--usa/cup.txt"
CHAMPIONS_LEAGUE_REPO = "https://github.com/openfootball/champions-league"


def remove_narrow_score_questions(questions: list[dict]) -> list[dict]:
    """Drop low-value questions whose only task is recalling an exact score."""
    score_markers = (
        "Как завершился матч ",
        "какой счёт был в матче ",
    )
    return [
        question for question in questions
        if not any(question.get("question", "").startswith(marker) for marker in score_markers)
    ]
OPENTDB_URL = "https://opentdb.com/api.php?" + urlencode({"amount": 50, "category": 21, "type": "multiple", "encode": "url3986"})
FOOTBALL_DATASETS_REPO = "https://github.com/datasets/football-datasets"
FOOTBALL_LEAGUES = {
    "premier-league": "Премьер-лига Англии",
    "la-liga": "Ла Лига",
    "serie-a": "Серия A",
    "bundesliga": "Бундеслига",
    "ligue-1": "Лига 1",
}


def fetch(url: str) -> str:
    if url == OPENTDB_URL and LOCAL_OPENTDB:
        return Path(LOCAL_OPENTDB).read_text(encoding="utf-8")
    if url == OPENFOOTBALL_URL and LOCAL_OPENFOOTBALL:
        return Path(LOCAL_OPENFOOTBALL).read_text(encoding="utf-8")
    if url == OPENFOOTBALL_1994_URL and LOCAL_OPENFOOTBALL_1994:
        return Path(LOCAL_OPENFOOTBALL_1994).read_text(encoding="utf-8")
    request = Request(url, headers={"User-Agent": "simple-quiz-importer/1.0"})
    with urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
        return response.read().decode("utf-8")


def clean(value: str) -> str:
    return html.unescape(unquote(value)).strip()


def import_opentdb() -> list[dict]:
    payload = json.loads(fetch(OPENTDB_URL))
    questions = []
    for item in payload.get("results", []):
        options = [clean(item["correct_answer"])] + [clean(value) for value in item["incorrect_answers"]]
        correct = options[0]
        # Stable shuffle keeps the checked answer index reproducible in the committed file.
        options = sorted(options, key=lambda value: (value.casefold(), value))
        questions.append({
            "question": clean(item["question"]),
            "options": options,
            "correct": options.index(correct),
            "explanation": f"Correct answer: {correct}.",
            "answer_verified": True,
            "source": "Open Trivia DB",
            "source_url": "https://opentdb.com/api_config.php",
            "license": "CC BY-SA 4.0",
            "checked_at": CHECKED_AT,
            "category": "Sports",
            "source_id": f"opentdb:{item.get('question', '')}",
        })
    return questions


def import_openfootball() -> list[dict]:
    text = fetch(OPENFOOTBALL_URL)
    groups = {}
    for line in text.splitlines():
        match = re.match(r"^Group ([A-L])\s*\|\s*(.+)$", line.strip())
        if match:
            teams = re.split(r"\s{2,}", match.group(2).strip())
            groups[match.group(1)] = [team.strip() for team in teams if team.strip()]

    questions = []
    all_teams = [team for teams in groups.values() for team in teams]
    for group, teams in groups.items():
        correct = ", ".join(teams)
        distractors = [", ".join(groups[key]) for key in groups if key != group]
        options = [correct] + distractors[:3]
        questions.append({
            "question": f"Какие сборные входят в группу {group} чемпионата мира 2026?",
            "options": options,
            "correct": 0,
            "explanation": f"Группа {group}: {correct}.",
            "answer_verified": True,
            "source": "openfootball/worldcup",
            "source_url": "https://github.com/openfootball/worldcup",
            "license": "CC0-1.0 (public domain)",
            "checked_at": CHECKED_AT,
            "category": "Football / World Cup 2026",
            "source_id": f"openfootball:2026:group-{group}",
        })

    match_pattern = re.compile(
        r"^\s+\d{1,2}:\d{2}\s+UTC[+-]\d+\s+"
        r"(.+?)\s+(\d+)-(\d+)(?:\s+\([^)]*\))?\s+(.+?)\s+@\s+(.+)$"
    )
    seen_matches = set()
    for line in text.splitlines():
        match = match_pattern.match(line)
        if not match:
            continue
        home, home_score, away_score, away, venue = match.groups()
        home, away, venue = home.strip(), away.strip(), venue.strip()
        key = (home, home_score, away_score, away, venue)
        if key in seen_matches or home not in all_teams or away not in all_teams:
            continue
        seen_matches.add(key)
        score = f"{home_score}:{away_score}"
        score_options = [score]
        for distractor in [f"{away_score}:{home_score}", "0:0", "2:1", "1:2", "3:1"]:
            if distractor not in score_options:
                score_options.append(distractor)
            if len(score_options) == 4:
                break
        questions.append({
            "question": f"Как завершился матч {home} — {away} на ЧМ-2026?",
            "options": score_options,
            "correct": 0,
            "explanation": f"Матч проходил на стадионе {venue}: {home} {home_score}:{away_score} {away}.",
            "answer_verified": True,
            "source": "openfootball/worldcup",
            "source_url": OPENFOOTBALL_URL,
            "license": "CC0-1.0 (public domain)",
            "checked_at": CHECKED_AT,
            "category": "Football / World Cup 2026",
            "source_id": f"openfootball:2026:match:{home}:{away}:{venue}",
        })
    return questions


def import_historical_leagues() -> list[dict]:
    """Import a compact, checked sample from the latest completed 2024/25 season."""
    questions = []
    for league_slug, league_name in FOOTBALL_LEAGUES.items():
        path = Path(LOCAL_FOOTBALL_DATASETS) / "datasets" / league_slug / "season-2425.csv" if LOCAL_FOOTBALL_DATASETS else None
        if path:
            rows = list(csv.DictReader(path.open(encoding="utf-8")))
        else:
            url = f"https://raw.githubusercontent.com/datasets/football-datasets/main/datasets/{league_slug}/season-2425.csv"
            rows = list(csv.DictReader(fetch(url).splitlines()))
        for row in rows[:12]:
            home, away = row["HomeTeam"].strip(), row["AwayTeam"].strip()
            home_score, away_score = row["FTHG"].strip(), row["FTAG"].strip()
            if not home or not away or not home_score.isdigit() or not away_score.isdigit():
                continue
            score = f"{home_score}:{away_score}"
            options = [score]
            for distractor in [f"{away_score}:{home_score}", "0:0", "1:0", "2:1", "1:2"]:
                if distractor not in options:
                    options.append(distractor)
                if len(options) == 4:
                    break
            questions.append({
                "question": f"Как завершился матч {home} — {away} в сезоне 2024/25 ({league_name})?",
                "options": options,
                "correct": 0,
                "explanation": f"{row['Date']}: {home} {home_score}:{away_score} {away}.",
                "answer_verified": True,
                "source": "datasets/football-datasets",
                "source_url": f"{FOOTBALL_DATASETS_REPO}/tree/main/datasets/{league_slug}",
                "license": "Open Data Commons PDDL 1.0",
                "checked_at": CHECKED_AT,
                "category": f"Football / {league_name}",
                "source_id": f"football-datasets:{league_slug}:2024-25:{row['Date']}:{home}:{away}",
            })
    return questions


def import_channel_inspired() -> list[dict]:
    """Create original questions around the channel's World Cup 1994 theme."""
    text = fetch(OPENFOOTBALL_1994_URL)
    pattern = re.compile(
        r"^\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .&'’()-]+?)\s+(\d+)-(\d+)\s+"
        r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .&'’()-]+?)\s+@\s+(.+)$"
    )
    questions = []
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        home, home_score, away_score, away, venue = [value.strip() for value in match.groups()]
        score = f"{home_score}:{away_score}"
        options = [score]
        for distractor in [f"{away_score}:{home_score}", "0:0", "1:0", "2:1", "1:2"]:
            if distractor not in options:
                options.append(distractor)
            if len(options) == 4:
                break
        questions.append({
            "question": f"В тематическом раунде ЧМ-1994: какой счёт был в матче {home} — {away}?",
            "options": options,
            "correct": 0,
            "explanation": f"ЧМ-1994, групповой этап, {venue}: {home} {home_score}:{away_score} {away}.",
            "answer_verified": True,
            "source": "openfootball/worldcup",
            "source_url": OPENFOOTBALL_1994_URL,
            "license": "CC0-1.0 (public domain)",
            "checked_at": CHECKED_AT,
            "category": "Football / World Cup 1994 / channel-inspired",
            "source_id": f"openfootball:1994:channel-inspired:{home}:{away}:{venue}",
            "inspired_by": "С двух ног — футбольная Своя игра (тематическая подборка)",
        })
        if len(questions) == 12:
            break
    return questions


def import_champions_league() -> list[dict]:
    """Import Champions League match facts from every checked-in season file."""
    if not LOCAL_CHAMPIONS_LEAGUE:
        return []
    pattern = re.compile(
        r"^\s+(?:\d{1,2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+(\d+[-–]\d+)"
    )
    questions = []
    finals = []
    for path in sorted(Path(LOCAL_CHAMPIONS_LEAGUE).glob("*/cl.txt")):
        season = path.parent.name
        stage = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("▪"):
                stage = line.strip()
            match = pattern.match(line)
            if not match:
                continue
            home, away, score = [value.strip() for value in match.groups()]
            home = re.sub(r"\s*\([A-Z]{3}\)$", "", home)
            away = re.sub(r"\s*\([A-Z]{3}\)$", "", away)
            if not home or not away:
                continue
            if stage in ("▪ Final", "▪ Finals, Final"):
                finals.append((season, home, away))
            score = score.replace("–", "-")
            home_score, away_score = score.split("-", 1)
            options = [score]
            for distractor in [f"{away_score}-{home_score}", "0-0", "1-0", "2-1", "1-2"]:
                if distractor not in options:
                    options.append(distractor)
                if len(options) == 4:
                    break
            questions.append({
                "question": f"Как завершился матч {home} — {away} в Лиге чемпионов сезона {season}?",
                "options": options,
                "correct": 0,
                "explanation": f"Лига чемпионов {season}: {home} {score} {away}.",
                "answer_verified": True,
                "source": "openfootball/champions-league",
                "source_url": f"{CHAMPIONS_LEAGUE_REPO}/blob/master/{season}/cl.txt",
                "license": "CC0-1.0 (public domain)",
                "checked_at": CHECKED_AT,
                "category": "Football / UEFA Champions League",
                "source_id": f"champions-league:{season}:{home}:{away}:{score}",
            })
    finalist_options = [f"{home} — {away}" for _, home, away in finals]
    for season, home, away in finals:
        correct = f"{home} — {away}"
        options = [correct]
        for distractor in finalist_options:
            if distractor != correct and distractor not in options:
                options.append(distractor)
            if len(options) == 4:
                break
        if len(options) < 4:
            continue
        questions.append({
            "question": f"Какие команды играли в финале Лиги чемпионов сезона {season}?",
            "options": options,
            "correct": 0,
            "explanation": f"В финале сезона {season} встретились {home} и {away}.",
            "answer_verified": True,
            "source": "openfootball/champions-league",
            "source_url": f"{CHAMPIONS_LEAGUE_REPO}/blob/master/{season}/cl.txt",
            "license": "CC0-1.0 (public domain)",
            "checked_at": CHECKED_AT,
            "category": "Football / UEFA Champions League / Finals",
            "source_id": f"champions-league:{season}:finalists",
        })
    return questions


def main() -> int:
    global LOCAL_OPENTDB, LOCAL_OPENFOOTBALL, LOCAL_OPENFOOTBALL_1994, LOCAL_FOOTBALL_DATASETS, LOCAL_CHAMPIONS_LEAGUE, LOCAL_BASE
    if "--base-file" in sys.argv:
        LOCAL_BASE = sys.argv[sys.argv.index("--base-file") + 1]
    if "--opentdb-file" in sys.argv:
        LOCAL_OPENTDB = sys.argv[sys.argv.index("--opentdb-file") + 1]
    if "--openfootball-file" in sys.argv:
        LOCAL_OPENFOOTBALL = sys.argv[sys.argv.index("--openfootball-file") + 1]
    if "--openfootball-1994-file" in sys.argv:
        LOCAL_OPENFOOTBALL_1994 = sys.argv[sys.argv.index("--openfootball-1994-file") + 1]
    if "--football-datasets-dir" in sys.argv:
        LOCAL_FOOTBALL_DATASETS = sys.argv[sys.argv.index("--football-datasets-dir") + 1]
    if "--champions-league-dir" in sys.argv:
        LOCAL_CHAMPIONS_LEAGUE = sys.argv[sys.argv.index("--champions-league-dir") + 1]
    sys.path.insert(0, str(ROOT / "pdmb_bot"))
    from question_quality import deduplicate_questions

    imported = (json.loads(Path(LOCAL_BASE).read_text(encoding="utf-8")) if LOCAL_BASE else
                import_opentdb() + import_openfootball() + import_historical_leagues() + import_channel_inspired())
    imported += import_champions_league()
    imported = remove_narrow_score_questions(imported)
    questions, report = deduplicate_questions(imported)
    if report["invalid"] or not questions:
        raise SystemExit(f"Quality check failed: {report}")
    OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "output": str(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
