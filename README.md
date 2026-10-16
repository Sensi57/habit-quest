# Habit Quest

A gamified habit tracker API. Create habits, check in daily, build streaks, earn XP and level up.

**Stack:** Flask + Gunicorn (backend), PostgreSQL 16 (database), Docker Compose.

## Run

```bash
cp .env.example .env      # then edit POSTGRES_PASSWORD
docker compose up --build
```

API is available at http://localhost:8000.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (queries the DB) |
| GET | `/habits` | List habits with streak, XP, level |
| POST | `/habits` | Create habit `{"name": "Read", "emoji": "📚"}` |
| POST | `/habits/<id>/checkin` | Check in `{"day": "YYYY-MM-DD", "note": "..."}` (both optional) |
| GET | `/habits/<id>/stats` | Detailed stats + last 10 check-ins |
| DELETE | `/habits/<id>` | Delete habit and its check-ins |
| GET | `/leaderboard` | Habits ranked by XP |

XP = 10 per check-in + 5 per day of longest streak. Level = XP / 100 + 1.

## Try it

```bash
curl -X POST localhost:8000/habits -H 'Content-Type: application/json' \
  -d '{"name":"Study Docker","emoji":"🐳"}'
curl -X POST localhost:8000/habits/1/checkin -H 'Content-Type: application/json' -d '{}'
curl localhost:8000/habits/1/stats
```

## Persistence test

```bash
docker compose down      # containers removed, named volume `pgdata` kept
docker compose up -d
curl localhost:8000/habits   # data is still there
```

Use `docker compose down -v` only if you want to wipe the data.

## Design notes

- Only the backend publishes a port; the database is reachable only on the internal `backend-net` network.
- Backend waits for the DB healthcheck (`depends_on: condition: service_healthy`) and also retries on startup.
- Secrets live in `.env` (git-ignored); `.env.example` has placeholders only.
# habit-quest
