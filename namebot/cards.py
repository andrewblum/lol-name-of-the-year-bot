"""Discord message formatting."""

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
