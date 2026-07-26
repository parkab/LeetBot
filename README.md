# LeetBot

A Discord bot that posts the LeetCode Daily Challenge every morning and walks users through a three-step mock interview (brute force → optimal technique → code) graded by Gemini AI. Scores are tracked on daily, all-time, and practice leaderboards.

Beyond the daily problem, `/grind75` and `/paretoset` pull random problems from curated LeetCode lists so you can drill on demand.

---

## Setup

### 1. Discord Application

1. Go to https://discord.com/developers/applications and create a new application.
2. **Bot** tab → Create a bot → copy the token → `DISCORD_TOKEN`.
3. Enable **Message Content Intent** (required for reading answers in threads/DMs).
4. **OAuth2 → URL Generator** — scopes: `bot`, `applications.commands`.  
   Permissions: Send Messages, Embed Links, Add Reactions, Read Message History, Create Public Threads, Send Messages in Threads.
5. Use the generated URL to invite the bot to your server.
6. Enable **Developer Mode** in Discord (Settings → Advanced), then right-click your server → **Copy Server ID** → `DISCORD_GUILD_ID`.
7. Right-click the channel where the daily problem should post → **Copy Channel ID** → `DAILY_CHANNEL_ID`.

### 2. API Keys

- **Gemini** — https://aistudio.google.com/app/apikey → `GEMINI_API_KEY`
- **Your Discord user ID** — Developer Mode → right-click yourself → Copy ID → `BOT_OWNER_ID`

### 3. Local Development

```bash
cp .env.example .env
# Fill in all values in .env

pip install -r requirements-dev.txt
pytest          # runs all tests (no API keys needed)
python -m leetbot.main
```

### 4. Fly.io Deployment

```bash
fly launch --no-deploy
fly volumes create leetbot_data --size 1 --region iad
fly secrets set \
  DISCORD_TOKEN=... \
  DISCORD_GUILD_ID=... \
  DAILY_CHANNEL_ID=... \
  GEMINI_API_KEY=... \
  BOT_OWNER_ID=... \
fly deploy
```

---

## Commands

| Command | Description |
|---------|-------------|
| `/daily` | Repost today's problem embed. |
| `/solve [private:bool]` | Start a mock interview on today's problem. |
| `/grind75` | Practice a random problem from the Grind 75 list. |
| `/paretoset` | Practice a random problem from the Pareto set. |
| `/giveup` | Skip the current step, see its solution, and move on. |
| `/explain <question>` | Ask a follow-up question about a solution. |
| `/leaderboard daily` | Top 10 for today. |
| `/leaderboard alltime` | Top 10 all-time by daily points. |
| `/leaderboard practice` | Top 10 by practice points. |
| `/stats [user]` | Daily and practice points side by side. |
| `/linear` | Very important command. |
| `/rate <activity>` | Mommy judges what you did today. |
| `/forcedaily` *(owner)* | Force-post today's problem immediately. |
| `/reload` *(owner)* | Reload all cogs without restarting the bot. |
| `/resetattempt [user] [practice]` *(owner)* | Wipe someone's attempt so they can retry. |

---

## Interview Flow

Each `/solve` creates a thread off the daily post where only the solving user's messages are routed for grading.

| Step | Max Points | Retry Penalty | Floor |
|------|----------:|--------------|-------|
| Brute Force | 15 | −3 | 0 |
| Technique | 25 | −5 | 0 |
| Code | 60 | −10 | 10 |

Max total: **100 pts**. Use `/giveup` to lock in partial credit and reveal the reference solution for each individual step.

### Grading criteria

The three steps are graded on deliberately different bars:

- **Brute force & technique — strict on complexity.** You must state **both** time *and* space complexity, and both must be correct *for the approach you described*. Omitting either one is a rejection. Equivalent phrasings all count (`O(n)`, `O(N)`, `O(2n)`, "linear"), and a correct `O(n²)` for a genuine brute force is correct — you're judged against your own approach, not the optimal one.
- **Code — lenient, logic only.** Pseudocode is fully acceptable, in any language. Syntax errors, missing imports, missing `class Solution` wrappers, informal lines like `for each x in arr`, and unhandled edge cases never cause a rejection. Rejections are reserved for genuinely wrong algorithms or non-attempts. You are not asked to restate complexity here.

---

## Practice Mode

`/grind75` and `/paretoset` open a thread, ask which difficulty you want, then serve a random problem you haven't finished yet.

- The difficulty picker only offers difficulties the list actually contains — the Pareto set has no Hard problems, so it shows Easy / Medium / Any.
- **🔁 Different Problem** rerolls to another problem at the same difficulty and resets your progress on that thread.
- Grading, hints, `/giveup`, and the 100-point scale are identical to the daily flow.
- Scores land in a separate practice leaderboard, keyed per problem. Only your **personal best** per problem is kept, so re-solving something can raise your score but never lower it, and problems appearing in both lists are only ever counted once.

---

## Environment Variables

See `.env.example` for the full list. All variables there are **required**, the bot fails loudly on startup if any are missing.
