import pytest

from namebot.parsing import InvalidSubmission, Submission, parse_submission


@pytest.mark.parametrize('content, expected', [
    ('name: Teemothy#Teeto', Submission('Teemothy', 'Teeto')),
    ('NAME:Teemothy #Teeto', Submission('Teemothy', 'Teeto')),
    ('  Name :  xX Big Gank Xx#NA1  ', Submission('xX Big Gank Xx', 'NA1')),
    ('name: `Teemothy#Teeto`', Submission('Teemothy', 'Teeto')),
    ('name: Teemothy#Teeto\nlmaooo this guy', Submission('Teemothy', 'Teeto')),
    ('name: Teemothy', Submission('Teemothy', 'NA1', tag_defaulted=True)),
    ('name: has#hash#TAG', Submission('has#hash', 'TAG')),
])
def test_parses_submissions(content, expected):
    assert parse_submission(content) == expected


@pytest.mark.parametrize('content', [
    'that name is so good',
    'lol name: Teemothy#Teeto',
    'names: Teemothy#Teeto',
    'his name: was crazy\nname: Foo#NA1',
])
def test_ignores_chat(content):
    assert parse_submission(content) is None


@pytest.mark.parametrize('content', ['name: ab#NA1', 'name: Teemothy#T', 'name: Teemothy#TOOLONG', 'name: x' * 20])
def test_rejects_malformed(content):
    with pytest.raises(InvalidSubmission):
        parse_submission(content)
