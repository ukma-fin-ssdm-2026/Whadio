import unicodedata
from typing import Final

# Unicode White_Space, which pydantic-core's `strip_whitespace` removes; bare `str.strip()` would
# also remove U+001C-U+001F and so accept names the API refuses.
_WHITE_SPACE: Final = (
    "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)
_VISIBLE_CATEGORIES: Final = frozenset("LNPS")
# Graphic characters that render blank: the Hangul fillers and the Braille blank.
_BLANK_GRAPHICS: Final = frozenset("\u115f\u1160\u3164\uffa0\u2800")


def display_text(value: str) -> str:
    """Return `value` without surrounding white space.

    Raises `ValueError` when it holds a control character or nothing visible.
    """
    value = value.strip(_WHITE_SPACE)
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError("must not contain control characters such as line breaks")
    if not any(
        unicodedata.category(char)[0] in _VISIBLE_CATEGORIES and char not in _BLANK_GRAPHICS
        for char in value
    ):
        raise ValueError("must contain a visible character, not only spaces or invisible ones")
    return value
