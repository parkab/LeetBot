# CLAUDE.md — LeetCode Interview Discord Bot

## Project Overview

A Discord bot for a small friend-group server (~20 people) that:
1. Posts the **LeetCode Daily Challenge** every morning at 9am ET.
2. Walks each user through an **interview-style solving flow** powered by the Gemini API — brute force explanation → optimal technique → code — with retries, hints, partial credit, and a 100-point max per problem.
3. Serves **on-demand practice problems** from curated LeetCode lists via `/grind75` and `/paretoset`.
4. Tracks scores via a **daily leaderboard**, an **all-time leaderboard**, and a separate **practice leaderboard**.
5. Has a few fun/prank commands (extensible).

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
| LeetCode source  | LeetCode GraphQL — `activeDailyCodingChallengeQuestion`, `question`, `favoriteQuestionList` |
| LLM              | Gemini API (`google-genai` SDK, `=gemini-3.1-flash-lite`) |
| Storage          | SQLite on Fly persistent volume           |
| Scheduling       | `discord.ext.tasks` in-process loop       |
| Hosting          | Fly.io                                    |

**Gemini model note:** `gemini-2.0-flash` has quota 0 on this account. `gemini-1.5-flash` is not available on v1beta for this account. `gemini-3.1-flash-lite` works and is the current default. The system prompt is embedded directly in the content string (not via `system_instruction`) for v1beta compatibility.

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
    ├── leetcode.py              # GraphQL: fetch_daily, fetch_question, fetch_problem_list
    ├── problemlists.py          # grind75/pareto registry, 6h TTL cache, problem selection
    ├── interview/
    │   ├── __init__.py
    │   ├── session.py           # InterviewSession state machine, Mode, PendingPractice
    │   ├── manager.py           # session registry (by user/key, by channel, pending threads)
    │   ├── flow.py              # SHARED interview machinery — used by daily AND practice
    │   ├── gemini.py            # Gemini client, grading, hints, step solutions, ref solution
    │   └── prompts.py           # all prompt templates — single source of truth
    ├── cogs/
    │   ├── daily.py             # daily loop, /solve, /daily, /giveup, /explain, on_message, DailyView
    │   ├── practice.py          # /grind75, /paretoset, DifficultyView, ProblemView
    │   ├── leaderboard.py       # /leaderboard daily|alltime|practice, /stats
    │   ├── fun.py               # /linear, /rate, derpshrines auto-react
    │   └── admin.py             # /reload, /forcedaily, /resetattempt (owner-only)
    └── utils/
        ├── time.py              # today_key() — YYYY-MM-DD in configured TIMEZONE
        └── format.py            # html_to_text, build_daily_embed, build_practice_embed, extract_code_block
```

### Where the interview logic lives

`interview/flow.py` owns everything identical between daily and practice:
`step_embed`, `HintView`, `handle_answer`, `finish_session`, `handle_giveup`, and
`ensure_reference_solution`. It branches on `session.mode` only where the two modes
genuinely differ — which table the score lands in, and the completion embed text.

There is exactly **one** `on_message` listener (in `daily.py`). It routes by channel,
so it serves practice threads too. Do NOT add a second listener in `practice.py` —
both would fire on the same message.

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

-- Practice problems pulled from curated lists. Keyed by slug and shared across
-- users, so a statement and its reference solution are fetched/generated once.
CREATE TABLE IF NOT EXISTS practice_problems (
    slug               TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    difficulty         TEXT NOT NULL,
    url                TEXT NOT NULL,
    content_html       TEXT NOT NULL,
    reference_solution TEXT,
    fetched_at         TEXT NOT NULL
);

-- One scored row per user per problem, regardless of which list served it.
CREATE TABLE IF NOT EXISTS practice_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL,
    list_name     TEXT NOT NULL,      -- 'grind75' | 'pareto'
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL,
    difficulty    TEXT NOT NULL,
    points        INTEGER NOT NULL,
    bf_retries    INTEGER NOT NULL DEFAULT 0,
    tech_retries  INTEGER NOT NULL DEFAULT 0,
    code_retries  INTEGER NOT NULL DEFAULT 0,
    completed_at  TEXT NOT NULL,
    UNIQUE(user_id, slug)
);
```

In-progress sessions live **in memory only** — bot restart = start over. One scored row per user per day in `attempts`.

`record_practice_attempt` uses `ON CONFLICT ... WHERE excluded.points > points`, so a
repeat only overwrites the row when the new score is **strictly higher**. That makes the
practice leaderboard a personal-best board and keeps `UNIQUE(user_id, slug)` from
double-counting problems that appear in both lists (e.g. Two Sum). It returns `True`
only when the row actually improved.

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
- Each answer is routed by `on_message` → `SessionManager.get_by_channel()` → `flow.handle_answer()`.
- On **accept**: advance state, send ✅ feedback embed, send next step embed with HintView.
- On **reject**: increment retry counter, send ❌ feedback embed, resend current step embed with HintView (so the hint button is always visible without scrolling).
- On **rate_limited** verdict: surface the retry-in-X-seconds message, don't advance or penalize.

### Points & Retries

| Step        | Max pts | Penalty  | Floor |
|-------------|--------:|----------|-------|
| Brute Force |      15 | −3/retry |     0 |
| Technique   |      25 | −5/retry |     0 |
| Code        |      60 | −10/retry|    10 |

Score = `max(floor, max − penalty × retries)` per step, summed. Identical for daily and practice.

### Grading criteria (per step)

The bar is deliberately **different per step** — this is the core of the prompt design
in `prompts.py`, and changing it changes how the whole bot feels.

**brute_force / technique — strict on complexity:**
- Both time AND space complexity are **mandatory**. Omitting either is an automatic reject,
  and the feedback must name which one was missing.
- Complexity is judged against **the approach the candidate described**, not the optimal
  one — a correct `O(n²)` for a genuine brute force is correct.
- Equivalent notations all accepted: `O(n)` = `O(N)` = `O(2n)` = "linear". Constant factors
  and lower-order terms never matter. Different orders of growth do.
- Claiming `O(1)` space while allocating a hash map is a reject.

**code — lenient, logic only:**
- Pseudocode is fully acceptable, in any language.
- Syntax errors, missing imports, missing `class Solution` wrapper, undefined obvious
  helpers, informal lines (`for each x in arr`), naming/style, missing edge cases, and
  off-by-ones with clear intent **never** cause a reject.
- Complexity is **not** required on this step.
- Reject only for a genuinely wrong algorithm, a non-attempt that just restates the
  technique, or a reversion to brute force after agreeing on the optimal approach.
- The prompt explicitly says "when in doubt, ACCEPT."

Verified against live Gemini with 13 representative cases (missing/wrong/plain-English
complexities, broken-syntax-but-correct code, informal pseudocode, wrong algorithms) —
all 13 produced the intended verdict.

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

**Practice problems do NOT generate one up front** — that would burn a Gemini call on every
reroll. `flow.ensure_reference_solution()` produces it the first time it's actually needed
(code-step grading, `/giveup` on code, or session completion) and caches it in
`practice_problems.reference_solution` by slug, so it's free for everyone afterwards.

---

## Practice Mode (`/grind75`, `/paretoset`)

### Problem sources

Both are **public** LeetCode problem lists ("favorites"), fetched with the
`favoriteQuestionList` GraphQL query — no auth required.

| Command | List slug | Size | Difficulty split |
|---|---|---:|---|
| `/grind75` | `rab78cw1` | 75 | 23 Easy / 43 Medium / 9 Hard |
| `/paretoset` | `2yvx2ha6` | 49 | 18 Easy / 31 Medium / **0 Hard** |

Neither list contains paid-only problems, but `problemlists.get_problems()` filters
`paid_only` anyway. Lists are cached in memory for 6 hours; a failed refetch falls back
to the stale cache so a LeetCode blip doesn't take the commands down.

### Flow

1. `/grind75` or `/paretoset` opens a thread and registers a `PendingPractice` (no session yet).
2. A `DifficultyView` is posted **in the thread**. It only shows difficulties the list
   actually contains, plus 🎲 Any — this is why `/paretoset` shows no Hard button.
3. Picking a difficulty selects a random problem the user hasn't completed
   (`db.get_completed_practice_slugs`), builds the real `InterviewSession`, and posts the
   problem embed + step 1. If every problem at that difficulty is done, it serves a repeat
   and says so.
4. **🔁 Different Problem** (`ProblemView`) rerolls to another problem at the same
   difficulty, excluding the current one. It swaps the problem onto the existing session,
   calls `session.reset_progress()`, and `manager.rekey()`s it — channel routing survives.
5. Everything after that is the shared `flow.py` path, identical to daily.

Only **one practice thread per user** at a time — `_start_practice` checks both live
sessions and pending threads.

### Session keying

`InterviewSession.session_key` is the day key for daily sessions and `practice:{slug}` for
practice ones, so a user can hold a daily thread and a practice thread simultaneously
without collision. `get_by_user_day()` deliberately returns `None` for practice sessions.

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
| `/grind75`               | anyone | Practice thread on a random Grind 75 problem |
| `/paretoset`             | anyone | Practice thread on a random Pareto set problem |
| `/giveup`                | anyone | Skip current step (0 pts), see solution, advance. Routed **by channel** — works in daily and practice threads. |
| `/explain <question>`    | anyone | Free-form Q&A. Uses the thread's problem when run inside a session, else today's. |
| `/leaderboard daily`     | anyone | Top 10 today by pts, tiebreak by earliest completion |
| `/leaderboard alltime`   | anyone | Top 10 by total daily pts |
| `/leaderboard practice`  | anyone | Top 10 by practice pts (personal best per problem) |
| `/stats [user]`          | anyone | Daily + practice breakdown and combined points |
| `/linear`                | anyone | Posts 😄 |
| `/rate <activity>`       | anyone | Mommy judges what you did |
| `/forcedaily`            | owner  | Manually trigger today's post |
| `/reload`                | owner  | Hot-reload all cogs |
| `/resetattempt [user] [practice]` | owner | Delete a user's daily attempt + clear in-memory sessions. `practice:True` also wipes their whole practice history. |

### Auto-reactions

`on_message` in `cogs/fun.py`: if `message.author.id == DERPSHRINES_USER_ID`, react with 🤓.

---

## HTML → Discord Markdown

`utils/format.py` uses a recursive `_node_to_md()` function (not `get_text(separator="\n")`) to convert LeetCode HTML to Discord markdown. Inline elements (`<strong>`, `<em>`, `<code>`) stay inline and render as `**bold**`, `*italic*`, `` `code` ``. Block elements (`<p>`, `<li>`, `<pre>`, `<br>`) add newlines. This prevents each bolded/code word from appearing on its own line.

---

## Persistent Views

All four views use `timeout=None` and stable `custom_id="persistent:..."` strings, and are registered in `bot.setup_hook()` via `self.add_view()` so they survive bot restarts:

| View | Location | Buttons |
|---|---|---|
| `DailyView` | `cogs/daily.py` | 🎯 Start Interview |
| `HintView` | `interview/flow.py` | 💡 Get Hint |
| `DifficultyView` | `cogs/practice.py` | Easy / Medium / Hard / 🎲 Any |
| `ProblemView` | `cogs/practice.py` | 🔁 Different Problem |

`DifficultyView(available=None)` keeps all four buttons — that's the instance registered
for persistence. The instance actually sent to a thread is constructed with the list's
available difficulties and has the missing buttons removed. Since practice state is
in-memory only, a post-restart click resolves to a clean "no longer active" message
rather than a failed interaction.

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

111 tests via `pytest` + `pytest-asyncio`. Run with:
```
python -m pytest tests/ -q
```

Test files: `test_db.py`, `test_gemini.py`, `test_leetcode.py`, `test_session.py`,
`test_time.py`, `test_problemlists.py`, `test_practice_db.py`, `test_practice_session.py`.
All mocked — no real API keys or network needed.

---

## Code Style additions

- Do NOT add a second `on_message` listener — `daily.py` owns the only one and routes by channel.
- Do NOT put interview logic in a cog; it belongs in `interview/flow.py` so both modes share it.
- Do NOT generate a reference solution eagerly for practice problems — use
  `flow.ensure_reference_solution()` so rerolls stay free.
- Persistent views need static `custom_id`s; never build them from runtime data.

---

*Last updated: 2026-07-26 (practice mode via /grind75 + /paretoset; stricter complexity
grading on brute force/technique; logic-only lenient grading on code)*
