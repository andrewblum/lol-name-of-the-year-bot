"""Discord message formatting."""

import calendar
import sqlite3

import discord

from . import bracket
from .periods import month_label
from .riot import opgg_url

CARD_COLOR = 0xC89B3C  # League gold


def riot_id(row: sqlite3.Row) -> str:
    return f'{row["game_name"]}#{row["tag_line"]}'


def jump_url(guild_id: int, row: sqlite3.Row) -> str | None:
    if not row['card_message_id']:
        return None
    return f'https://discord.com/channels/{guild_id}/{row["card_channel_id"]}/{row["card_message_id"]}'


def name_link(guild_id: int, row: sqlite3.Row) -> str:
    """Links to the submission card in Discord, falling back to op.gg."""
    return f'[{riot_id(row)}]({jump_url(guild_id, row) or opgg_url(row["game_name"], row["tag_line"])})'


def name_card(row: sqlite3.Row, *, icon_url: str | None, vote_emoji: str, verified: bool,
              tag_defaulted: bool) -> discord.Embed:
    embed = discord.Embed(
        title=riot_id(row), url=opgg_url(row['game_name'], row['tag_line']), color=CARD_COLOR
    )
    if verified:
        embed.add_field(name='Rank', value=row['rank'] or 'Unranked')
        embed.add_field(name='Level', value=str(row['level'] or '?'))
    else:
        embed.description = "⚠️ Couldn't reach Riot to verify this account; added anyway."
    if tag_defaulted:
        embed.add_field(name='Tag', value='No #tag given; assumed #NA1', inline=False)
    embed.add_field(name='Submitted by', value=f'<@{row["submitted_by"]}>', inline=False)
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.set_footer(text=f'React {vote_emoji} to vote · Name of the Month: {month_label(row["month"])}')
    return embed


def leaderboard(title: str, rows: list[sqlite3.Row], guild_id: int, vote_emoji: str) -> discord.Embed:
    embed = discord.Embed(title=title, color=CARD_COLOR)
    if not rows:
        embed.description = 'No names yet. Post one with `name: Teemothy#Teeto`.'
        return embed
    medals = ['🥇', '🥈', '🥉']
    embed.description = '\n'.join(
        f'{medals[i] if i < 3 else f"`{i + 1}.`"} {name_link(guild_id, r)} · {r["votes"]} {vote_emoji}'
        for i, r in enumerate(rows)
    )
    return embed


def bracket_board(year: int, total_rounds: int, matches: list[sqlite3.Row], names: dict[int, sqlite3.Row],
                  seeds: dict[int, int]) -> discord.Embed:
    def label(name_id: int | None) -> str:
        if name_id is None:
            return '(bye)'
        return f'({seeds[name_id]}) {riot_id(names[name_id])}'

    embed = discord.Embed(title=f'🏆 Name of the Year {year}', color=CARD_COLOR)
    for round_ in range(1, total_rounds + 1):
        lines = []
        for m in (m for m in matches if m['round'] == round_):
            a, b = label(m['a_id']), label(m['b_id'])
            if m['winner_id'] is None:
                lines.append(f'{a}  vs  {b}')
            elif m['b_id'] is None:
                lines.append(f'**{a}** (bye)')
            else:
                a, b = (f'**{a}**', b) if m['winner_id'] == m['a_id'] else (a, f'**{b}**')
                lines.append(f'{a} {m["a_votes"]}–{m["b_votes"]} {b}')
        if lines:
            embed.add_field(name=bracket.round_name(round_, total_rounds), value='\n'.join(lines)[:1024],
                            inline=False)
    return embed


def help_embed(names_channel_id: int, vote_emoji: str, bracket_size: int, round_hours: int,
               bracket_start: tuple[int, int] | None) -> discord.Embed:
    embed = discord.Embed(
        title='🏆 Name of the Year: how it works',
        description='Spot a cursed or hilarious name in a game? Submit it, vote on everyone else\'s, and we '
                    'crown a **Name of the Month** and, at the end of the year, a **Name of the Year**.',
        color=CARD_COLOR,
    )
    embed.add_field(
        name='📝 Submit a name',
        value=f'Post in <#{names_channel_id}>:\n`name: Teemothy#Teeto`\n'
              'The message has to **start with** `name:`. Everything else in the channel is just chat, so '
              'roast away. No `#tag`? The bot assumes `#NA1`. NA accounts only. '
              'The bot replies with a card showing rank, level, and an op.gg link, and catches duplicates '
              '(even renamed accounts).',
        inline=False,
    )
    embed.add_field(
        name=f'{vote_emoji} Vote',
        value=f'React {vote_emoji} on a name\'s card. One vote per person per name; un-react to take it back.',
        inline=False,
    )
    embed.add_field(
        name='👑 Name of the Month',
        value='On the 1st, the top-voted name submitted the previous month wins and gets a guaranteed spot '
              'in the year-end bracket.',
        inline=False,
    )
    when = (f'On {calendar.month_abbr[bracket_start[0]]} {bracket_start[1]}' if bracket_start
            else 'After the year ends')
    embed.add_field(
        name='🏆 Name of the Year',
        value=f'{when}, up to {bracket_size} names (every Name of the Month plus the top vote-getters) go '
              f'into a bracket seeded by votes. Each matchup is a Discord poll, {round_hours}h per round, '
              'and ties go to the higher seed.',
        inline=False,
    )
    embed.add_field(
        name='⌨️ Commands',
        value='`/top` leaderboard (this month, this year, or all time)\n'
              '`/random` a random name from the archive\n'
              '`/halloffame` every Name of the Month and Name of the Year\n'
              '`/bracket` the current or most recent bracket\n'
              '`/help` this message',
        inline=False,
    )
    return embed
