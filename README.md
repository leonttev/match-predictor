# Match Predictor — система прогнозирования матчей (Dota 2)

Прогнозирование исхода профессиональных матчей Dota 2 на основе рейтинга
команд, начисляемого за результаты с учётом тира турнира, и их текущей
формы — по истории матчей из [OpenDota API](https://docs.opendota.com/).

Проект выполнен для курса «Расширенные возможности языков высокого уровня»
(см. [reports/lab1_topic.md](reports/lab1_topic.md) и
[reports/lab2_architecture.md](reports/lab2_architecture.md) для обоснования
темы и архитектуры).

## Архитектура

```
┌──────────┐     ┌─────────┐     ┌───────────────────┐     ┌──────────┐
│ Frontend │────▶│ Backend │────▶│ DB interaction     │────▶│ Postgres │
│ React/TS │     │ FastAPI │     │ module (FastAPI)   │     │          │
└──────────┘     │ (auth,  │     └───────────────────┘     └──────────┘
                  │ 2FA,    │
                  │ async   │     ┌───────────────────┐
                  │ orches- │────▶│ Prediction engine  │
                  │ tration)│     │ (Go, functional    │
                  └────┬────┘     │ module: рейтинг +  │
                       │          │ win-probability)    │
                       ▼          └───────────────────┘
                 OpenDota API
                 (внешний источник данных)
```

| Компонент | Технология | Роль |
|---|---|---|
| `frontend/` | React + TypeScript (Vite) | UI: логин/регистрация, 2FA, список команд, прогноз матча |
| `backend/` | Python (FastAPI, async) | Авторизация/аутентификация + 2FA (TOTP), оркестрация сетевых вызовов к остальным сервисам, приём данных из OpenDota |
| `db-service/` | Python (FastAPI, SQLAlchemy) | Единственный компонент, обращающийся к БД напрямую |
| `prediction-engine/` | Go (net/http, goroutines) | Функциональный модуль: рейтинг команд + вероятность победы |
| БД | SQLite (dev) / PostgreSQL (prod, `docker-compose.yml`) | Хранение команд, матчей, прогнозов, пользователей |

Обоснование выбора языков и разделения на компоненты — в
[reports/lab2_architecture.md](reports/lab2_architecture.md).

## Запуск локально (без Docker)

Требуется: Python 3.12+, Go 1.22+, Node 20+.

```bash
# 1. Функциональный модуль (Go)
cd prediction-engine
go build -o prediction-engine.exe .
PORT=8090 ./prediction-engine.exe &

# 2. Модуль работы с БД (Python, SQLite по умолчанию)
cd ../db-service
python -m venv .venv && ./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/python -m uvicorn app.main:app --port 8081 &

# 3. Бэкенд (Python)
cd ../backend
python -m venv .venv && ./.venv/Scripts/pip install -r requirements.txt
APP_DB_SERVICE_URL=http://localhost:8081 APP_PREDICTION_ENGINE_URL=http://localhost:8090 \
  ./.venv/Scripts/python -m uvicorn app.main:app --port 8000 &

# 4. Фронтенд
cd ../frontend
npm install
npm run dev
```

Открыть `http://localhost:5173`, зарегистрироваться, войти, нажать
«Обновить данные и пересчитать рейтинги» (тянет актуальные команды/матчи с
OpenDota), затем построить прогноз.

## Запуск через Docker (продакшен-конфигурация, PostgreSQL)

```bash
docker compose up --build
```

## API (бэкенд, `backend/app/routers`)

- `POST /auth/register`, `POST /auth/login` — регистрация и вход (пароль хешируется PBKDF2-HMAC)
- `POST /auth/2fa/setup`, `POST /auth/2fa/enable`, `POST /auth/2fa/login` — включение и прохождение двухфакторной аутентификации (TOTP, совместимо с Google Authenticator)
- `GET /teams`, `GET /matches` — данные, полученные через DB interaction module
- `POST /predict` — прогноз исхода матча между двумя командами (обращается к `prediction-engine`)
- `POST /ingest/run` — загрузка свежих данных с OpenDota и пересчёт рейтингов

Все защищённые эндпоинты требуют `Authorization: Bearer <JWT>`, выданный
только после прохождения 2FA (если она включена для пользователя).

## Модель прогнозирования (`prediction-engine`)

1. **Рейтинг команды** — стартовое значение по тиру команды (tier 1 → 1000,
   tier 2 → 750, tier 3 → 500, тир не определён → 250) плюс очки за
   результаты последних 20 матчей, где цена результата зависит от тира
   матча: tier 1 — +50/−25, tier 2 — +25/−13, tier 3 — +13/−7, иначе +7/−4.
2. **Текущая форма** — доля побед за последние 5 матчей. Рейтинг и форма
   считаются параллельно по всем командам (пул горутин).
3. **Вероятность победы** — логистическая функция от разницы рейтингов
   (масштаб 1000) с небольшой добавкой формы (вес 0.1).

Константы масштаба и веса формы подобраны по историческим данным
скриптом [scripts/calibrate.py](scripts/calibrate.py) (хронологическое
разбиение 70/30, минимизация log loss), а не назначены на глаз. Разбор
модели, метрики и их честная интерпретация —
в [reports/lab2_architecture.md](reports/lab2_architecture.md).

```bash
python scripts/calibrate.py   # требует запущенных db-service и prediction-engine
```

## Известные ограничения

- **Точность прогноза статистически не отличается от случайного угадывания**
  (47.9% против 48.3% у «всегда 50%» на отложенной выборке из 545 матчей).
  Предыдущая реализация на Elo, измеренная так же, даёт тот же результат.
  Причины и что потребовалось бы для улучшения — в отчёте по ЛР №2/№7.
- Бесплатный OpenDota API не отдаёт официальное расписание предстоящих
  профессиональных матчей, поэтому прогноз строится «по запросу» для любой
  пары команд, а история матчей используется для расчёта рейтингов.
- Состав команды достраивается до пяти игроков по числу игр, если OpenDota
  подтверждает меньше: у команд с долгой историей в состав может попасть
  бывший игрок.
- SQLite используется для локальной разработки; для стенда защиты — Postgres
  через `docker-compose.yml`.
