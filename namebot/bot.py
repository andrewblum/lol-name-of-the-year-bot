"""The Discord bot: submissions, vote tracking, Name of the Month, Name of the Year bracket."""

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from . import bracket, cards
from .config import Config
from .db import Database
from .parsing import InvalidSubmission, Submission, parse_submission
from .periods import month_key, month_label, utcnow
from .riot import RiotClient, RiotUnavailable

log = logging.getLogger(__name__)

# How long past a poll's expiry we wait for Discord to finalize its counts before using them anyway.
POLL_FINALIZE_GRACE = timedelta(minutes=15)


class NameBot(discord.Client):
    def __init__(self, cfg: Config):
        intents = discord.Intents.default()
        intents.message_content = True  # privileged: toggle it on in the Developer Portal
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False),
        )
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.tree = app_commands.CommandTree(self)
        self.guild_obj = discord.Object(id=cfg.guild_id)
        self.http_session: aiohttp.ClientSession | None = None
        self.riot: RiotClient | None = None
        # Serializes the scheduler with admin commands that touch the bracket.
        self.bracket_lock = asyncio.Lock()

    async def setup_hook(self):
        from .commands import register

        self.http_session = aiohttp.ClientSession()
        self.riot = RiotClient(self.cfg.riot_api_key, self.http_session)
        register(self)
        await self.tree.sync(guild=self.guild_obj)
        self.scheduler.start()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def on_ready(self):
        log.info('Logged in as %s; watching channel %s', self.user, self.cfg.names_channel_id)

    async def channel(self, channel_id: int) -> discord.abc.Messageable:
        return self.get_channel(channel_id) or await self.fetch_channel(channel_id)

    # -- submissions ---------------------------------------------------------------

    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id != self.cfg.names_channel_id:
            return
        try:
            submission = parse_submission(message.content)
        except InvalidSubmission as exc:
            await message.reply(f'{exc} Format: `name: Teemothy#Teeto`')
            return
        if submission:
            await self.handle_submission(message, submission)

    async def handle_submission(self, message: discord.Message, sub: Submission):
        async with message.channel.typing():
            profile, verified = None, True
            try:
                profile = await self.riot.lookup(sub.game_name, sub.tag_line)
            except RiotUnavailable as exc:
                log.warning('Riot unavailable, accepting %s#%s unverified: %s', sub.game_name, sub.tag_line, exc)
                verified = False
            if verified and profile is None:
                await message.reply(f"Couldn't find an NA account named **{sub.game_name}#{sub.tag_line}**. Typo?")
                return

            game_name, tag_line = (profile.game_name, profile.tag_line) if profile else (sub.game_name, sub.tag_line)
            duplicate = self.db.find_duplicate(profile.puuid if profile else None, game_name, tag_line)
            if duplicate:
                await self.reply_duplicate(message, duplicate)
                return

            now = utcnow()
            try:
                name_id = self.db.add_name(
                    puuid=profile.puuid if profile else None, game_name=game_name, tag_line=tag_line,
                    submitted_by=message.author.id, submitted_at=now, month=month_key(now, self.cfg.tz),
                    level=profile.level if profile else None, icon_id=profile.icon_id if profile else None,
                    rank=profile.rank if profile else None,
                )
            except sqlite3.IntegrityError:  # lost a race with an identical submission
                duplicate = self.db.find_duplicate(profile.puuid if profile else None, game_name, tag_line)
                if duplicate:
                    await self.reply_duplicate(message, duplicate)
                return

            row = self.db.get_name(name_id)
            embed = cards.name_card(
                row, icon_url=await self.riot.icon_url(row['icon_id']), vote_emoji=self.cfg.vote_emoji,
                verified=verified, tag_defaulted=sub.tag_defaulted,
            )
            try:
                card = await message.reply(embed=embed)
            except discord.HTTPException:
                self.db.delete_name(name_id)
                raise
            self.db.set_card(name_id, card.channel.id, card.id)
        try:
            await card.add_reaction(self.cfg.vote_emoji)
        except discord.HTTPException:
            log.exception('Could not add vote reaction to card %s', card.id)

    async def reply_duplicate(self, message: discord.Message, row: sqlite3.Row):
        link = cards.jump_url(self.cfg.guild_id, row)
        await message.reply(
            f'**{cards.riot_id(row)}** was already submitted by <@{row["submitted_by"]}>'
            + (f' → {link}' if link else '') + f'. Go {self.cfg.vote_emoji} it there.',
            suppress_embeds=True,
        )

    # -- votes (reactions on the bot's name cards) -------------------------------------

    def _vote_target(self, payload: discord.RawReactionActionEvent) -> sqlite3.Row | None:
        if payload.user_id == self.user.id or str(payload.emoji) != self.cfg.vote_emoji:
            return None
        return self.db.name_by_card(payload.message_id)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        row = self._vote_target(payload)
        if row and not (payload.member and payload.member.bot):
            self.db.add_vote(row['id'], payload.user_id)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        row = self._vote_target(payload)
        if row:
            self.db.remove_vote(row['id'], payload.user_id)

    async def reconcile_votes(self, row: sqlite3.Row):
        """Re-read a card's reactions so votes cast while the bot was offline still count."""
        if not row['card_message_id']:
            return
        try:
            channel = await self.channel(row['card_channel_id'])
            msg = await channel.fetch_message(row['card_message_id'])
        except (discord.NotFound, discord.Forbidden):
            return  # card gone; keep whatever votes we tracked
        reaction = discord.utils.find(lambda r: str(r.emoji) == self.cfg.vote_emoji, msg.reactions)
        voters = [u.id async for u in reaction.users() if not u.bot] if reaction else []
        self.db.replace_votes(row['id'], voters)

    # -- scheduler ----------------------------------------------------------------------

    @tasks.loop(minutes=5)
    async def scheduler(self):
        async with self.bracket_lock:
            for step in (self.decide_months, self.maybe_start_bracket, self.advance_bracket):
                try:
                    await step()
                except Exception:
                    log.exception('scheduler step %s failed', step.__name__)

    @scheduler.before_loop
    async def _before_scheduler(self):
        await self.wait_until_ready()

    # -- Name of the Month ----------------------------------------------------------------

    async def decide_months(self):
        """Crown every finished month that hasn't been decided yet (catches up after downtime)."""
        current = month_key(utcnow(), self.cfg.tz)
        for month in self.db.undecided_months(current):
            for row in self.db.names_in_month(month):
                await self.reconcile_votes(row)
            top = self.db.top_names(month=month, limit=3)
            if not top:
                self.db.record_monthly_winner(month, None, 0, utcnow())
                continue
            winner = top[0]
            self.db.record_monthly_winner(month, winner['id'], winner['votes'], utcnow())

            embed = discord.Embed(
                title=f'👑 Name of the Month: {month_label(month)}',
                description=(
                    f'## {cards.name_link(self.cfg.guild_id, winner)}\n'
                    f'{winner["votes"]} {self.cfg.vote_emoji} · submitted by <@{winner["submitted_by"]}>\n'
                    'Auto-qualified for the Name of the Year bracket.'
                ),
                color=cards.CARD_COLOR,
            )
            if len(top) > 1:
                embed.add_field(
                    name='Runners-up',
                    value='\n'.join(f'{cards.name_link(self.cfg.guild_id, r)} · {r["votes"]} {self.cfg.vote_emoji}'
                                    for r in top[1:]),
                )
            icon = await self.riot.icon_url(winner['icon_id'])
            if icon:
                embed.set_thumbnail(url=icon)
            await (await self.channel(self.cfg.announce_channel_id)).send(embed=embed)

    # -- Name of the Year bracket -------------------------------------------------------------

    async def maybe_start_bracket(self):
        if not self.cfg.bracket_start:
            return
        now = utcnow().astimezone(self.cfg.tz)
        year = now.year - 1
        if (now.month, now.day) < self.cfg.bracket_start or self.db.get_bracket(year):
            return
        # Wait for December to be crowned so its winner makes the bracket.
        if f'{year}-12' in self.db.undecided_months(month_key(utcnow(), self.cfg.tz)):
            return
        if len(self.db.bracket_entrants(year, self.cfg.bracket_size)) >= 2:
            await self.start_bracket(year)

    async def start_bracket(self, year: int) -> str:
        """Seed and open a bracket. Caller must hold bracket_lock. Returns a status line."""
        if self.db.get_bracket(year):
            return f'The {year} bracket already exists.'
        if self.db.active_bracket():
            return 'Another bracket is still running.'
        entrants = self.db.bracket_entrants(year, self.cfg.bracket_size)
        if len(entrants) < 2:
            return f'Need at least 2 names from {year} to run a bracket.'

        ids = [r['id'] for r in entrants]
        size = bracket.bracket_size(len(ids), self.cfg.bracket_size)
        self.db.create_bracket(year, ids, bracket.total_rounds(size), utcnow(), bracket.first_round(ids, size))

        channel = await self.channel(self.cfg.announce_channel_id)
        await channel.send(
            f'# 🏆 Name of the Year {year} starts now\n'
            f'{len(ids)} names: every Name of the Month plus the top vote-getters. '
            f'One poll per matchup, {self.cfg.round_hours}h per round. Ties go to the higher seed.',
            embed=self.bracket_embed(year),
        )
        await self.post_round_polls(year, 1)
        return f'Started the {year} bracket with {len(ids)} names.'

    def bracket_embed(self, year: int) -> discord.Embed:
        b = self.db.get_bracket(year)
        seeds = self.db.seeds(year)
        names = {name_id: self.db.get_name(name_id) for name_id in seeds}
        return cards.bracket_board(year, b['total_rounds'], self.db.matches(year), names, seeds)

    async def post_round_polls(self, year: int, round_: int):
        b = self.db.get_bracket(year)
        seeds = self.db.seeds(year)
        title = bracket.round_name(round_, b['total_rounds'])
        channel = await self.channel(self.cfg.announce_channel_id)
        for m in self.db.matches(year, round_):
            if m['winner_id'] is not None or m['poll_message_id'] is not None:
                continue
            a, other = self.db.get_name(m['a_id']), self.db.get_name(m['b_id'])
            duration = timedelta(hours=self.cfg.round_hours)
            poll = discord.Poll(question=f'Name of the Year {year} · {title} · Match {m["slot"] + 1}',
                                duration=duration)
            for row in (a, other):
                poll.add_answer(text=f'({seeds[row["id"]]}) {cards.riot_id(row)}'[:55])
            msg = await channel.send(
                f'{cards.name_link(self.cfg.guild_id, a)}  vs  {cards.name_link(self.cfg.guild_id, other)}',
                poll=poll,
            )
            ends_at = msg.poll.expires_at if msg.poll and msg.poll.expires_at else utcnow() + duration
            self.db.set_match_poll(m['id'], channel.id, msg.id, ends_at)

    async def read_poll(self, m: sqlite3.Row) -> tuple[int, int, bool]:
        """(a_votes, b_votes, finalized). A deleted poll counts as 0-0, i.e. the higher seed advances."""
        try:
            channel = await self.channel(m['poll_channel_id'])
            msg = await channel.fetch_message(m['poll_message_id'])
        except discord.NotFound:
            log.warning('Poll message for match %s is gone; scoring 0-0', m['id'])
            return 0, 0, True
        if not msg.poll or len(msg.poll.answers) < 2:
            return 0, 0, True
        answers = msg.poll.answers
        return answers[0].vote_count, answers[1].vote_count, msg.poll.is_finalized()

    async def advance_bracket(self):
        b = self.db.active_bracket()
        if not b:
            return
        year, round_ = b['year'], b['current_round']
        matches = self.db.matches(year, round_)

        # Polls that never got posted (e.g. crash mid-round) — post them and come back later.
        if any(m['winner_id'] is None and m['poll_message_id'] is None for m in matches):
            await self.post_round_polls(year, round_)
            return

        seeds = self.db.seeds(year)
        now = utcnow()
        for m in matches:
            if m['winner_id'] is not None or now < datetime.fromisoformat(m['ends_at']):
                continue
            a_votes, b_votes, finalized = await self.read_poll(m)
            if not finalized and now < datetime.fromisoformat(m['ends_at']) + POLL_FINALIZE_GRACE:
                continue
            winner = bracket.pick_winner(m['a_id'], m['b_id'], a_votes, b_votes, seeds)
            self.db.decide_match(m['id'], winner, a_votes, b_votes)

        matches = self.db.matches(year, round_)
        if any(m['winner_id'] is None for m in matches):
            return

        channel = await self.channel(self.cfg.announce_channel_id)
        winners = [m['winner_id'] for m in matches]
        if len(winners) == 1:
            self.db.finish_bracket(year, winners[0])
            champ = self.db.get_name(winners[0])
            await channel.send(
                f'# 🏆 {year} Name of the Year: {cards.name_link(self.cfg.guild_id, champ)}\n'
                f'Submitted by <@{champ["submitted_by"]}>. Congrats/condolences to the account owner.',
                embed=self.bracket_embed(year),
            )
            return

        self.db.open_round(year, round_ + 1, bracket.next_round(winners))
        next_name = bracket.round_name(round_ + 1, b['total_rounds'])
        await channel.send(
            f'**{bracket.round_name(round_, b["total_rounds"])}: done.** On to the {next_name}:',
            embed=self.bracket_embed(year),
        )
        await self.post_round_polls(year, round_ + 1)
