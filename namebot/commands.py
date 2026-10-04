"""Slash commands (registered to the one guild so they show up instantly)."""

from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands

from . import cards
from .periods import month_key, month_label, utcnow

if TYPE_CHECKING:
    from .bot import NameBot


def register(bot: 'NameBot'):
    cfg, db, guild = bot.cfg, bot.db, bot.guild_obj

    @bot.tree.command(name='help', description='What this bot is and how to use it', guild=guild)
    @app_commands.describe(public='Post it for everyone (e.g. to pin in the channel) instead of just you')
    async def help_(interaction: discord.Interaction, public: bool = False):
        await interaction.response.send_message(
            embed=cards.help_embed(cfg.names_channel_id, cfg.vote_emoji, cfg.bracket_size, cfg.round_hours,
                                   cfg.bracket_start),
            ephemeral=not public,
        )

    @bot.tree.command(name='top', description='Top-voted names', guild=guild)
    @app_commands.describe(period='Which period (default: this month)')
    async def top(interaction: discord.Interaction, period: Literal['month', 'year', 'all'] = 'month'):
        now = utcnow()
        if period == 'month':
            key = month_key(now, cfg.tz)
            rows, title = db.top_names(month=key), f'Top names: {month_label(key)}'
        elif period == 'year':
            year = now.astimezone(cfg.tz).year
            rows, title = db.top_names(year=year), f'Top names: {year}'
        else:
            rows, title = db.top_names(), 'Top names: all time'
        await interaction.response.send_message(
            embed=cards.leaderboard(title, rows, cfg.guild_id, cfg.vote_emoji)
        )

    @bot.tree.command(name='random', description='Pull a random name from the archive', guild=guild)
    async def random_(interaction: discord.Interaction):
        row = db.random_name()
        if not row:
            await interaction.response.send_message('No names yet.', ephemeral=True)
            return
        await interaction.response.send_message(
            f'🎲 {cards.name_link(cfg.guild_id, row)} · {row["votes"]} {cfg.vote_emoji} · '
            f'submitted by <@{row["submitted_by"]}> in {month_label(row["month"])}',
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @bot.tree.command(name='halloffame', description='Names of the Month and Names of the Year', guild=guild)
    async def halloffame(interaction: discord.Interaction):
        embed = discord.Embed(title='🏛️ Hall of Fame', color=cards.CARD_COLOR)
        year_lines = [f'**{r["year"]}**: {cards.name_link(cfg.guild_id, r)}' for r in db.year_winners()]
        month_lines = [f'{month_label(r["month"])}: {cards.name_link(cfg.guild_id, r)} · {r["votes"]} {cfg.vote_emoji}'
                       for r in db.monthly_winners()]
        embed.add_field(name='🏆 Name of the Year', value='\n'.join(year_lines) or 'None yet', inline=False)
        # Embed fields cap at 1024 chars; show the most recent months if the list gets long.
        month_text = '\n'.join(month_lines[-12:]) or 'None yet'
        embed.add_field(name='👑 Name of the Month', value=month_text[-1024:], inline=False)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name='bracket', description='Show the current (or most recent) Name of the Year bracket',
                      guild=guild)
    async def show_bracket(interaction: discord.Interaction):
        b = db.active_bracket() or db.latest_bracket()
        if not b:
            await interaction.response.send_message('No bracket yet. It kicks off after the year ends.',
                                                    ephemeral=True)
            return
        await interaction.response.send_message(embed=bot.bracket_embed(b['year']))

    @bot.tree.command(name='bracket-start', description='Admin: start a Name of the Year bracket now',
                      guild=guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(year='Which year of names (default: this year)')
    async def bracket_start(interaction: discord.Interaction, year: int | None = None):
        await interaction.response.defer(ephemeral=True)
        async with bot.bracket_lock:
            status = await bot.start_bracket(year or utcnow().astimezone(cfg.tz).year)
        await interaction.followup.send(status, ephemeral=True)

    @bot.tree.command(name='remove-name', description='Admin: remove a submission (dupes, trolls)',
                      guild=guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(name='Start typing to search submitted names')
    async def remove_name(interaction: discord.Interaction, name: str):
        row = db.name_by_riot_id(name)
        if not row:
            await interaction.response.send_message(f'No submission found for `{name}`.', ephemeral=True)
            return
        db.remove_name(row['id'])
        await interaction.response.send_message(f'Removed **{cards.riot_id(row)}**.', ephemeral=True)

    @remove_name.autocomplete('name')
    async def remove_name_autocomplete(interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=cards.riot_id(r), value=cards.riot_id(r))
                for r in db.search_names(current)]
