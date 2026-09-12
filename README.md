# Match Predictor — система прогнозирования матчей (Dota 2)

Прогнозирование исхода профессиональных матчей Dota 2 на основе Elo-рейтинга
команд и их текущей формы, рассчитанных по истории матчей из [OpenDota
API](https://docs.opendota.com/).

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
                  └────┬────┘     │ module: Elo +      │
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
| `prediction-engine/` | Go (net/http, goroutines) | Функциональный модуль: Elo-рейтинг + вероятность победы |
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
- `POST /ingest/run` — загрузка свежих данных с OpenDota и пересчёт Elo-рейтингов

Все защищённые эндпоинты требуют `Authorization: Bearer <JWT>`, выданный
только после прохождения 2FA (если она включена для пользователя).

## Модель прогнозирования (`prediction-engine`)

1. **Elo-рейтинг** — последовательный проход по истории матчей команды
   (K=32, старт 1500), обновляется по каждому сыгранному матчу.
2. **Текущая форма** — доля побед за последние 5 матчей, считается
   параллельно по всем командам (пул горутин).
3. **Итоговая вероятность** — взвешенная комбинация логистической функции
   от разницы Elo (вес 0.7) и формы (вес 0.3).

## Известные ограничения

- Бесплатный OpenDota API не отдаёт официальное расписание предстоящих
  профессиональных матчей, поэтому прогноз строится «по запросу» для любой
  пары команд, а лента матчей показывает историю (на которой и обучается/
  валидируется модель), а не афишу будущих игр.
- SQLite используется для локальной разработки; для стенда защиты — Postgres
  через `docker-compose.yml`.
