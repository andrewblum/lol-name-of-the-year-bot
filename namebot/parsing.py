"""Recognizing `name: Foo#NA1` submissions in chat."""

import re
from dataclasses import dataclass

# Only the first line counts, and it must start with "name:" — so "name: Foo#NA1 lmao"
# on line one plus commentary below still works, while normal chat is ignored.
SUBMISSION = re.compile(r'^\s*name\s*:\s*(?P<rid>.+?)\s*$', re.IGNORECASE)
DEFAULT_TAG = 'NA1'


@dataclass(frozen=True)
class Submission:
    game_name: str
    tag_line: str
    tag_defaulted: bool = False


class InvalidSubmission(ValueError):
    pass


def parse_submission(content: str) -> Submission | None:
    """None if the message isn't a submission; raises InvalidSubmission if it's a malformed one."""
    first_line = content.strip().split('\n', 1)[0]
    match = SUBMISSION.match(first_line)
    if not match:
        return None

    rid = match.group('rid').strip('`"\'* ')
    if '#' in rid:
        game_name, tag_line = (part.strip() for part in rid.rsplit('#', 1))
        tag_defaulted = False
    else:
        game_name, tag_line, tag_defaulted = rid, DEFAULT_TAG, True

    # Riot IDs: game name 3-16 chars, tagline 3-5 alphanumerics.
    if not 3 <= len(game_name) <= 16:
        raise InvalidSubmission(f'"{game_name}" isn\'t a valid Riot name (3-16 characters).')
    if not re.fullmatch(r'[^\W_]{3,5}', tag_line):
        raise InvalidSubmission(f'"#{tag_line}" isn\'t a valid tagline (3-5 letters/numbers).')
    return Submission(game_name, tag_line, tag_defaulted)
