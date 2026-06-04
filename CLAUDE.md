# CLAUDE.md — LeetCode Interview Discord Bot

## Project Overview

A Discord bot for a small friend-group server (~20 people) that:
1. Posts the **LeetCode Daily Challenge** every morning at 9am ET.
2. Walks each user through an **interview-style solving flow** powered by the Gemini API — brute force explanation → optimal technique → Python code — with retries, hints, partial credit, and a 100-point max per problem.
3. Tracks scores via a **daily leaderboard** and an **all-time leaderboard**.
4. Has a few fun/prank commands (extensible).

Target: **fast command response, 24/7 uptime, low cost.**

---

## ⚠️ Hosting Note

Hosted on **Fly.io** — single shared-CPU-1x, 256 MB VM, 1 GB persistent volume at `/data`. As of late 2024 Fly no longer has a true free tier (~$2-5/month). The bot must never be auto-stopped or it disconnects from Discord.

---

## Stack

| Layer            | Choice                                    |
|------------------|-------------------------------------------|
| Language         | Python 3.11+                              |
| Discord lib      | discord.py v2.x                           |
| LeetCode source  | LeetCode GraphQL — `activeDailyCodingChallengeQuestion` |
| LLM              | Gemini API (`google-genai` SDK, `gemini-2.5-flash-lite`) |
| Storage          | SQLite on Fly persistent volume           |
| Scheduling       | `discord.ext.tasks` in-process loop       |
| Hosting          | Fly.io                                    |

**Gemini model note:** `gemini-2.0-flash` has quota 0 on this account. `gemini-1.5-flash` is not available on v1beta for this account. `gemini-2.5-flash-lite` works and is the current default. The system prompt is embedded directly in the content string (not via `system_instruction`) for v1beta compatibility.

---

## Repo Layout

```
LeetBot/
├── CLAUDE.md
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .env.example
├── .gitignore
├── fly.toml
├── Dockerfile
├── README.md
└── leetbot/
    ├── __init__.py
    ├── main.py                  # entrypoint: load env, build bot, run
    ├── bot.py                   # LeetBot subclass, cog loading, persistent view registration
    ├── config.py                # env var parsing, point/penalty constants
    ├── db.py                    # SQLite connection, schema, all query helpers
    ├── leetcode.py              # GraphQL client for daily challenge
    ├── interview/
    │   ├── __init__.py
    │   ├── session.py           # InterviewSession state machine
    │   ├── manager.py           # in-memory session registry (keyed by user/day and channel)
    │   ├── gemini.py            # Gemini client, grading, hints, step solutions, ref solution
    │   └── prompts.py           # all prompt templates — single source of truth
    ├── cogs/
    │   ├── daily.py             # daily post loop, /solve, /daily, /giveup, HintView, DailyView
    │   ├── leaderboard.py       # /leaderboard, /stats
    │   ├── fun.py               # /linear, derpshrines auto-react
    │   └── admin.py             # /reload, /forcedaily, /resetattempt (owner-only)
    └── utils/
        ├── time.py              # today_key() — YYYY-MM-DD in configured TIMEZONE
        └── format.py            # html_to_text (recursive markdown), build_daily_embed, extract_code_block
```

---

## Environment Variables

```
DISCORD_TOKEN=
DISCORD_GUILD_ID=           # guild-scoped slash command registration (instant updates)
DAILY_CHANNEL_ID=           # channel where daily problem is posted
GEMINI_API_KEY=             # get from aistudio.google.com (NOT Google Cloud Console) for free tier
GEMINI_MODEL=gemini-2.5-flash-lite
BOT_OWNER_ID=               # Discord user ID — gates admin commands
DERPSHRINES_USER_ID=        # user ID for the 🤓 auto-react prank
DAILY_POST_HOUR_UTC=13      # 13:00 UTC = 9am ET
TIMEZONE=America/New_York
DB_PATH=leetbot.db          # use /data/leetbot.db on Fly.io
```

`config.py` fails loudly on startup if any required var is missing.

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS problems (
    day_key            TEXT PRIMARY KEY,   -- 'YYYY-MM-DD' in TIMEZONE
    title              TEXT NOT NULL,
    slug               TEXT NOT NULL,
    difficulty         TEXT NOT NULL,
    url                TEXT NOT NULL,
    content_html       TEXT NOT NULL,      -- raw HTML from LeetCode (kept for reprocessing)
    posted_at          TEXT NOT NULL,      -- ISO8601
    reference_solution TEXT,               -- generated once by Gemini, cached
    message_id         TEXT               -- Discord message ID of the daily post
);

CREATE TABLE IF NOT EXISTS attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL,           -- Discord user ID as string
    day_key       TEXT NOT NULL,
    points        INTEGER NOT NULL,
    bf_retries    INTEGER NOT NULL DEFAULT 0,
    tech_retries  INTEGER NOT NULL DEFAULT 0,
    code_retries  INTEGER NOT NULL DEFAULT 0,
    completed_at  TEXT NOT NULL,
    UNIQUE(user_id, day_key)
);
```

In-progress sessions live **in memory only** — bot restart = start over. One scored row per user per day in `attempts`.

---

## Interview Flow

### Starting

`/solve` (or the "🎯 Start Interview" button on the daily post) calls `_start_solve_flow`. Each user gets their own standalone thread in the daily channel (via `channel.create_thread()` — NOT `message.create_thread()`, which only allows one thread per message). Multiple users can have threads open simultaneously.

Thread name format: `{display_name} — {day_key}`

If `private:True` is passed, opens a DM instead.

### State Machine

```
BRUTE_FORCE → TECHNIQUE → CODE → DONE
```

- User types answers as regular messages in their thread/DM. Messages starting with `#` are silently ignored (note-taking mode).
- Each answer is routed by `on_message` → `SessionManager.get_by_channel()` → `_handle_answer()`.
- On **accept**: advance state, send ✅ feedback embed, send next step embed with HintView.
- On **reject**: increment retry counter, send ❌ feedback embed, resend current step embed with HintView (so the hint button is always visible without scrolling).
- On **rate_limited** verdict: surface the retry-in-X-seconds message, don't advance or penalize.

### Points & Retries

| Step        | Max pts | Penalty  | Floor |
|-------------|--------:|----------|-------|
| Brute Force |      15 | −3/retry |     0 |
| Technique   |      25 | −5/retry |     0 |
| Code        |      60 | −10/retry|    10 |

Score = `max(floor, max − penalty × retries)` per step, summed.

### Hints

Each step embed has a "💡 Get Hint" button (persistent `HintView`). Hints are progressive:
- Hint 1: high-level nudge (no technique named)
- Hint 2: names the technique and why it applies
- Hint 3: full algorithm walkthrough in plain English (no code)

Hint count is tracked per step in the session.

### /giveup (per-step)

Skips the **current** step (awards 0 pts for it):
- For brute_force / technique: Gemini generates a plain-English solution explanation for the skipped step, then advances to the next step.
- For code: shows the reference solution, ends the session.

### Reference Solution

Generated once per problem by a separate Gemini call when the daily post is created, cached in `problems.reference_solution`. If the stored value is null/empty/"# Reference solution unavailable", it is lazily regenerated when a user starts `/solve`.

---

## Gemini Integration

All prompts in `interview/prompts.py`. Key design decisions:

- System prompt embedded in content string (not `system_instruction` param) — avoids v1beta incompatibilities.
- Response parsed as JSON; if parsing fails, retries once with "respond with valid JSON only" appended; if still fails, returns a generic reject verdict. Never crashes the session.
- 429/RESOURCE_EXHAUSTED returns a `rate_limited` verdict with retry delay surfaced to the user.

### Verdict JSON schema

```json
{
  "verdict": "accept" | "reject",
  "feedback": "3-4 sentences, educational and specific",
  "complexity_check": "brief note or null"
}
```

---

## Commands

| Command                  | Who    | What |
|--------------------------|--------|------|
| `/daily`                 | anyone | Reposts today's embed |
| `/solve [private:bool]`  | anyone | Starts interview thread (or DM). Blocked if already completed today. |
| `/giveup`                | anyone | Skip current step (0 pts), see solution, advance |
| `/leaderboard daily`     | anyone | Top 10 today by pts, tiebreak by earliest completion |
| `/leaderboard alltime`   | anyone | Top 10 by total pts |
| `/stats [user]`          | anyone | Days played, total pts, average |
| `/linear`                | anyone | Posts 😄 |
| `/forcedaily`            | owner  | Manually trigger today's post |
| `/reload`                | owner  | Hot-reload all cogs |
| `/resetattempt [user]`   | owner  | Delete a user's DB attempt + clear in-memory session for today (for testing) |

### Auto-reactions

`on_message` in `cogs/fun.py`: if `message.author.id == DERPSHRINES_USER_ID`, react with 🤓.

---

## HTML → Discord Markdown

`utils/format.py` uses a recursive `_node_to_md()` function (not `get_text(separator="\n")`) to convert LeetCode HTML to Discord markdown. Inline elements (`<strong>`, `<em>`, `<code>`) stay inline and render as `**bold**`, `*italic*`, `` `code` ``. Block elements (`<p>`, `<li>`, `<pre>`, `<br>`) add newlines. This prevents each bolded/code word from appearing on its own line.

---

## Persistent Views

Both `DailyView` (Start Interview button) and `HintView` (Get Hint button) use `timeout=None` and stable `custom_id="persistent:..."` strings. Both are registered in `bot.setup_hook()` via `self.add_view()` so they survive bot restarts.

---

## Fly.io Deployment

`fly.toml` key settings:
- No `[http_service]` — gateway-only bot, no exposed port
- `auto_stop_machines = false`, `min_machines_running = 1`
- Volume mounted at `/data`, set `DB_PATH=/data/leetbot.db` as a Fly secret

Deploy workflow:
```
fly secrets set DISCORD_TOKEN=... GEMINI_API_KEY=... # etc.
fly deploy
```

After any change that adds a new slash command, the command is synced to the guild automatically on bot startup. `/reload` hot-reloads cog logic without a full restart.

---

## Code Style

- Type hints everywhere.
- Async for all Discord/HTTP operations. `asyncio.to_thread()` wraps all SQLite calls.
- `logging` at INFO; one line per significant event.
- Constants in `config.py` — no magic numbers in cogs.
- No global mutable state except `bot.session_manager`.
- Do NOT run user-submitted code (`exec`, etc.) — Gemini grades by inspection only.
- Do NOT persist in-progress sessions to disk.
- Do NOT register slash commands globally (guild-scoped only during dev).
- Do NOT auto-stop the Fly machine.

---

## Tests

47 tests via `pytest` + `pytest-asyncio`. Run with:
```
python -m pytest tests/ -q
```

Test files: `test_db.py`, `test_gemini.py`, `test_leetcode.py`, `test_session.py`, `test_time.py`. All mocked — no real API keys needed.

---

*Last updated: 2026-06-04*
