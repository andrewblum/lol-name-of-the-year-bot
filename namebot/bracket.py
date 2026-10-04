"""Pure single-elimination bracket logic (no Discord, no DB)."""


def bracket_size(entrants: int, max_size: int) -> int:
    """Smallest power of two that fits everyone, capped at max_size."""
    size = 2
    while size < min(entrants, max_size):
        size *= 2
    return size


def total_rounds(size: int) -> int:
    return size.bit_length() - 1


def seed_order(size: int) -> list[int]:
    """Standard seeding so 1 and 2 can only meet in the final: 8 -> [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [s for seed in order for s in (seed, n + 1 - seed)]
    return order


def first_round(seeded_ids: list[int], size: int) -> list[tuple[int, int | None]]:
    """Pairs for round 1. Seeds past the entrant count are byes (None), which land on the top seeds."""
    by_seed = {seed: name_id for seed, name_id in enumerate(seeded_ids, start=1)}
    order = seed_order(size)
    return [(by_seed[order[i]], by_seed.get(order[i + 1])) for i in range(0, size, 2)]


def next_round(winners: list[int]) -> list[tuple[int, int]]:
    return [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]


def pick_winner(a_id: int, b_id: int, a_votes: int, b_votes: int, seeds: dict[int, int]) -> int:
    """More votes wins; a tie goes to the better (lower) seed."""
    if a_votes != b_votes:
        return a_id if a_votes > b_votes else b_id
    return a_id if seeds[a_id] < seeds[b_id] else b_id


def round_name(round_: int, rounds: int) -> str:
    remaining = rounds - round_
    if remaining == 0:
        return 'Final'
    if remaining == 1:
        return 'Semifinals'
    if remaining == 2:
        return 'Quarterfinals'
    return f'Round of {2 ** (remaining + 1)}'
