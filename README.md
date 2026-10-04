# 🏆 LoL Name of the Year

A Discord bot for collecting the funniest League names you run into, voting on them, crowning a
**Name of the Month** automatically, and running a bracket for **Name of the Year**.

## How it works

- **Submit:** in the names channel, post `name: Teemothy#Teeto`. Only messages whose *first line*
  starts with `name:` count, so normal chatting and roasting in the channel is ignored. If you leave off
  the `#tag`, the bot assumes `#NA1`.
- **Card:** the bot looks the account up with the Riot API (NA), rejects typos and accounts that don't
  exist, catches duplicates (even if the account has been renamed since), and replies with a card
  showing rank, level, profile icon, and an op.gg link.
- **Vote:** react 👍 on the card. One vote per person per name.
- **Name of the Month:** on the 1st (Pacific time), the bot crowns the top-voted name submitted last
  month and posts the runners-up.
- **Name of the Year:** on Jan 2, the bot seeds a bracket of up to 16 names: every Name of the Month
  gets in, and the remaining spots go to the year's top vote-getters. Seeding is by votes. Each
  matchup is a native Discord poll that runs 48h, ties go to the higher seed, and the bot advances
  rounds and posts the updated bracket on its own. With 16 entrants it takes about 8 days.

### Slash commands

| Command | Who | What |
|---|---|---|
| `/help [public]` | anyone | How the bot works and how to submit. Only you see it, unless `public:True` (post it once and pin it) |
| `/top [month\|year\|all]` | anyone | Leaderboard |
| `/random` | anyone | A random name from the archive |
| `/halloffame` | anyone | Every Name of the Month and Name of the Year |
| `/bracket` | anyone | The current or most recent bracket |
| `/bracket-start [year]` | Manage Server | Start a bracket now, e.g. a mid-year test run |
| `/remove-name Riot#ID` | Manage Server | Remove a troll or mistaken submission |

## Setup

### 1. Discord application

1. Go to <https://discord.com/developers/applications>, click **New Application**, and open **Bot**.
   **Reset Token**, then copy it into `DISCORD_TOKEN`.
2. On the same Bot page, turn on **Message Content Intent**. The bot needs it to read `name:` posts.
3. Under **OAuth2 → URL Generator**, select the scopes `bot` and `applications.commands`, then the
   bot permissions *View Channels, Send Messages, Embed Links, Add Reactions, Read Message History,
   Create Polls*. Or use this URL with your app ID filled in:
   `https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=562949953506368`
4. In Discord, turn on Developer Mode (Settings → Advanced). Then right-click the server for
   `GUILD_ID`, and the names channel for `NAMES_CHANNEL_ID`.

### 2. Riot API key

At <https://developer.riotgames.com>, register a **Personal API Key** product. Approval takes a few
days, and the key doesn't expire. The default dev key **expires every 24h**, which is fine for local
testing but not for an always-on bot. If the key is missing or expired, the bot still accepts names.
It marks them unverified and skips the rank, level, and icon.

### 3. Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # fill in DISCORD_TOKEN, GUILD_ID, NAMES_CHANNEL_ID, RIOT_API_KEY
python -m namebot
pytest                   # tests use a temp DB and fake Discord; they never touch your server
```

### 4. Deploy (Fly.io, about $2–3/month)

The bot needs one always-on process with a small persistent disk for SQLite.

```bash
brew install flyctl && fly auth login
# edit `app = ` in fly.toml to a unique name, then:
fly launch --no-deploy --copy-config
fly volumes create namebot_data --size 1 --region lax
fly secrets set DISCORD_TOKEN=... GUILD_ID=... NAMES_CHANNEL_ID=... RIOT_API_KEY=...
fly deploy
fly scale count 1        # exactly one instance, or every name gets two replies
fly logs
```

Back up the database with `fly ssh sftp get /data/names.sqlite3`.

Any host that can keep a Python process running works the same way, such as Railway or an Oracle
free-tier VM. Run `python -m namebot` with `DB_PATH` pointed at persistent storage.

## Configuration

See `.env.example` for all options. These are the ones you're most likely to change:

| Var | Default | |
|---|---|---|
| `ANNOUNCE_CHANNEL_ID` | names channel | Where monthly winners and bracket polls go |
| `BRACKET_SIZE` | `16` | Max entrants (power of 2). Fewer names → smaller bracket, byes for the top seeds |
| `ROUND_HOURS` | `48` | Poll length per round |
| `BRACKET_START` | `01-02` | When last year's bracket auto-starts. Blank = only via `/bracket-start` |
| `VOTE_EMOJI` | `👍` | Reaction that counts as a vote |
| `TIMEZONE` | `America/Los_Angeles` | Which timezone defines month boundaries |

## Layout

```
namebot/
  bot.py        Discord client: submissions, vote tracking, scheduler (monthly winner, bracket rounds)
  commands.py   slash commands
  db.py         SQLite schema + queries (names, votes, monthly_winners, brackets, matches)
  bracket.py    pure bracket math: seeding, byes, tie-breaks
  riot.py       async Riot API client (account → level / icon / rank), op.gg links
  parsing.py    `name: Foo#TAG` recognition
  cards.py      embeds
```

Votes are tracked live from reaction events. Before a month is decided, the bot re-reads every card's
reactions, so votes cast while it was down still count. If the bot is offline at a month boundary
or during a round, it catches up when it comes back.
