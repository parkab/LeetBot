# LeetBot

A Discord bot that posts the LeetCode Daily Challenge every morning and walks users through a three-step mock interview (brute force → optimal technique → code) graded by Gemini AI. Scores are tracked on daily and all-time leaderboards.

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
| `/giveup` | End your active session and lock in partial points. |
| `/leaderboard daily` | Top 10 for today. |
| `/leaderboard alltime` | Top 10 all-time by total points. |
| `/stats [user]` | Points, days played, average. |
| `/linear` | Very important command. |
| `/forcedaily` *(owner)* | Force-post today's problem immediately. |
| `/reload` *(owner)* | Reload all cogs without restarting the bot. |

---

## Interview Flow

Each `/solve` creates a thread off the daily post where only the solving user's messages are routed for grading.

| Step | Max Points | Retry Penalty | Floor |
|------|----------:|--------------|-------|
| Brute Force | 15 | −3 | 0 |
| Technique | 25 | −5 | 0 |
| Code | 60 | −10 | 10 |

Max total: **100 pts**. Use `/giveup` to lock in partial credit and reveal the reference solution.

---

## Environment Variables

See `.env.example` for the full list. All variables there are **required** — the bot fails loudly on startup if any are missing.
