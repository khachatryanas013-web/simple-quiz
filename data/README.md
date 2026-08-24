# Данные проекта

## `source/`

`Simple_Quiz_Intelligence_base.json` — исходная база из 48 вопросов и
справочные таблицы. Скрипт `scripts/enrich_telegram_questions.mjs` всегда
начинает сборку с этого файла, поэтому повторный запуск не создаёт дубликаты.

## Производные данные

Производные данные Telegram остаются в `telegram_archive/`:

- `manifest.json`;
- `question_analysis.tsv`;
- `questions.json`;
- `questions_enriched.json`;
- `questions.csv`.

## Внешние источники тренажёра

`pdmb_bot/external_questions.json` — зафиксированный снапшот вопросов, который
бот загружает локально и не запрашивает во время тренировки:

- футбольные группы и матчи — [openfootball/worldcup](https://github.com/openfootball/worldcup), CC0-1.0;
- общие спортивные вопросы — [Open Trivia DB](https://opentdb.com/api_config.php), CC BY-SA 4.0.

Каждая запись хранит `source`, `source_url`, `license`, `checked_at` и
`source_id`. Обновление выполняется командой:

```bash
python3 tools/import_external_questions.py
```

Импортёр выполняет структурную проверку, удаляет повторы и не сохраняет
вопросы без четырёх уникальных вариантов ответа и корректного индекса ответа.

Для обновления Лиги чемпионов передайте локальный клон репозитория:

```bash
git clone --depth 1 https://github.com/openfootball/champions-league.git /tmp/openfootball-champions-league
python3 tools/import_external_questions.py \
  --base-file pdmb_bot/external_questions.json \
  --champions-league-dir /tmp/openfootball-champions-league
```

Полный реестр источников и их статусы находится в
`data/football_sources.json`. В Telegram сейчас публикуются русскоязычные
вопросы из openfootball, включая финалы Лиги чемпионов и оригинальную тематическую подборку по ЧМ-1994
«в стиле футбольной Своей игры», и исторические результаты пяти лиг из
`datasets/football-datasets`. Формулировки выпусков канала «С двух ног» не
копируются. Узкие вопросы о точном счёте матчей намеренно исключаются.
SoccerData и StatsBomb сохранены как отдельный
будущий аналитический контур и не вызываются во время работы бота.

Медиа и сырые страницы не входят в Git и воспроизводятся скриптом архивации.
