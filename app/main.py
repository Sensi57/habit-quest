"""Habit Quest API: track habits, check in daily, earn XP and streaks."""
import os
import time
from datetime import date, timedelta

import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request

app = Flask(__name__)

DB_CONFIG = {
    "host": os.environ["POSTGRES_HOST"],
    "port": os.environ.get("POSTGRES_PORT", "5432"),
    "dbname": os.environ["POSTGRES_DB"],
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
}

XP_PER_CHECKIN = 10
XP_PER_LEVEL = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS habits (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(100) NOT NULL UNIQUE,
    emoji      VARCHAR(8) NOT NULL DEFAULT '⭐',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS checkins (
    id       SERIAL PRIMARY KEY,
    habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    day      DATE NOT NULL,
    note     TEXT,
    UNIQUE (habit_id, day)
);
"""


def get_conn():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db(retries=15, delay=2):
    for attempt in range(1, retries + 1):
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute(SCHEMA)
            print("Database ready", flush=True)
            return
        except psycopg2.OperationalError as exc:
            print(f"DB not ready (attempt {attempt}/{retries}): {exc}", flush=True)
            time.sleep(delay)
    raise RuntimeError("Could not connect to the database")


def compute_streaks(days):
    """Return (current_streak, longest_streak) from a list of dates."""
    if not days:
        return 0, 0
    day_set = set(days)
    longest = 0
    for d in day_set:
        if d - timedelta(days=1) not in day_set:  # start of a run
            length = 1
            while d + timedelta(days=length) in day_set:
                length += 1
            longest = max(longest, length)
    today = date.today()
    cursor = today if today in day_set else today - timedelta(days=1)
    current = 0
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def habit_stats(cur, habit_id):
    cur.execute("SELECT day FROM checkins WHERE habit_id = %s", (habit_id,))
    days = [r["day"] for r in cur.fetchall()]
    current, longest = compute_streaks(days)
    xp = len(days) * XP_PER_CHECKIN + longest * 5
    return {
        "total_checkins": len(days),
        "current_streak": current,
        "longest_streak": longest,
        "xp": xp,
        "level": xp // XP_PER_LEVEL + 1,
    }


@app.get("/")
def index():
    return jsonify(
        service="Habit Quest API",
        endpoints=[
            "GET  /health",
            "GET  /habits",
            "POST /habits            {name, emoji?}",
            "POST /habits/<id>/checkin {day?: YYYY-MM-DD, note?}",
            "GET  /habits/<id>/stats",
            "DELETE /habits/<id>",
            "GET  /leaderboard",
        ],
    )


@app.get("/health")
def health():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
    return jsonify(status="ok")


@app.get("/habits")
def list_habits():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, emoji, created_at FROM habits ORDER BY id")
        habits = cur.fetchall()
        for h in habits:
            h.update(habit_stats(cur, h["id"]))
    return jsonify(habits)


@app.post("/habits")
def create_habit():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify(error="'name' is required"), 400
    emoji = body.get("emoji") or "⭐"
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO habits (name, emoji) VALUES (%s, %s) "
                "RETURNING id, name, emoji, created_at",
                (name, emoji),
            )
            return jsonify(cur.fetchone()), 201
    except psycopg2.errors.UniqueViolation:
        return jsonify(error="habit already exists"), 409


@app.post("/habits/<int:habit_id>/checkin")
def checkin(habit_id):
    body = request.get_json(silent=True) or {}
    try:
        day = date.fromisoformat(body["day"]) if body.get("day") else date.today()
    except ValueError:
        return jsonify(error="'day' must be YYYY-MM-DD"), 400
    if day > date.today():
        return jsonify(error="cannot check in for the future"), 400
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM habits WHERE id = %s", (habit_id,))
        if not cur.fetchone():
            return jsonify(error="habit not found"), 404
        cur.execute(
            "INSERT INTO checkins (habit_id, day, note) VALUES (%s, %s, %s) "
            "ON CONFLICT (habit_id, day) DO NOTHING RETURNING id",
            (habit_id, day, body.get("note")),
        )
        created = cur.fetchone() is not None
        stats = habit_stats(cur, habit_id)
    status = 201 if created else 200
    msg = "Quest complete! +%d XP" % XP_PER_CHECKIN if created else "Already checked in that day"
    return jsonify(message=msg, day=day.isoformat(), **stats), status


@app.get("/habits/<int:habit_id>/stats")
def stats(habit_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, emoji FROM habits WHERE id = %s", (habit_id,))
        habit = cur.fetchone()
        if not habit:
            return jsonify(error="habit not found"), 404
        habit.update(habit_stats(cur, habit_id))
        cur.execute(
            "SELECT day, note FROM checkins WHERE habit_id = %s ORDER BY day DESC LIMIT 10",
            (habit_id,),
        )
        habit["recent_checkins"] = cur.fetchall()
    return jsonify(habit)


@app.delete("/habits/<int:habit_id>")
def delete_habit(habit_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM habits WHERE id = %s RETURNING id", (habit_id,))
        if not cur.fetchone():
            return jsonify(error="habit not found"), 404
    return jsonify(deleted=habit_id)


@app.get("/leaderboard")
def leaderboard():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, emoji FROM habits")
        habits = cur.fetchall()
        for h in habits:
            h.update(habit_stats(cur, h["id"]))
    habits.sort(key=lambda h: h["xp"], reverse=True)
    return jsonify(habits)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("APP_PORT", 8000)))
