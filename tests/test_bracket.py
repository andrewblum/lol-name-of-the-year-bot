from namebot import bracket


def test_seed_order_keeps_top_seeds_apart():
    assert bracket.seed_order(2) == [1, 2]
    assert bracket.seed_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    order = bracket.seed_order(16)
    assert sorted(order) == list(range(1, 17))
    assert order.index(1) < 8 <= order.index(2)  # 1 and 2 in opposite halves


def test_bracket_size():
    assert bracket.bracket_size(2, 16) == 2
    assert bracket.bracket_size(5, 16) == 8
    assert bracket.bracket_size(16, 16) == 16
    assert bracket.bracket_size(40, 16) == 16
    assert bracket.total_rounds(16) == 4


def test_first_round_gives_byes_to_top_seeds():
    ids = [101, 102, 103, 104, 105]  # seeds 1..5 in an 8-bracket -> seeds 1, 2, 3 get byes
    pairs = bracket.first_round(ids, 8)
    assert pairs == [(101, None), (104, 105), (102, None), (103, None)]


def test_next_round_pairs_adjacent_winners():
    assert bracket.next_round([1, 2, 3, 4]) == [(1, 2), (3, 4)]


def test_pick_winner_ties_go_to_better_seed():
    seeds = {10: 3, 20: 6}
    assert bracket.pick_winner(10, 20, 4, 7, seeds) == 20
    assert bracket.pick_winner(10, 20, 5, 5, seeds) == 10
    assert bracket.pick_winner(20, 10, 0, 0, seeds) == 10


def test_round_names():
    assert [bracket.round_name(r, 4) for r in range(1, 5)] == [
        'Round of 16', 'Quarterfinals', 'Semifinals', 'Final']
