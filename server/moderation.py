"""Content screen for public free-text submissions: slurs and profanity.

Blocks the class of garbage the apply form actually receives. Two tiers:

  * slurs are blocked in every screened field;
  * profanity is additionally blocked when ``strict=True``: identity
    fields (character / guild / Discord names, class + spec) and URLs,
    where profanity is never part of a sincere answer. Paragraph fields
    stay non-strict so "I fucking love raiding" doesn't bounce a real
    applicant.

Identity words (gay, trans, jew, ...) are deliberately absent: this
screens abuse, not people.

Matching tolerates the usual obfuscations: accents are stripped, common
leetspeak digits map back to letters, separators are ignored, repeated
letters are tolerated, and ``*``/``#``/``%`` act as masked-letter
wildcards when the term's first and last letters are literal (so
"n*gger" hits while a self-censored "f******g" in a paragraph doesn't).
Short terms that occur inside innocent words ("spic" in "conspicuous",
"rapist" in "therapist") match whole words only. This is deterrence
against drive-by trolls, not an unbeatable filter: a determined poster
can always outspell it; the admin delete button stays the backstop.

The term list is ROT13-encoded so this file doesn't drop raw slurs into
diffs, grep output, and GitHub code search. A readability choice, not
secrecy: the repo is public and the encoding is trivial.
"""
from __future__ import annotations

import codecs
import re
import unicodedata

# Leetspeak digits/symbols back to the letters they impersonate, plus the
# masked-letter characters normalized to a single wildcard.
_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "6": "g", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s", "!": "i", "|": "l",
    "#": "*", "%": "*",
})

# Anything that isn't a normalized letter or the mask wildcard splits words.
_SEP_RE = re.compile(r"[^a-z*]+")


def _rot13(terms: str) -> tuple[str, ...]:
    return tuple(codecs.decode(terms, "rot13").split())


# Blocked as substrings anywhere in the squeezed text: each term is
# distinctive enough that no innocent word or word-junction contains it.
_SLURS_ANY = _rot13(
    "avttre avttn snttbg xvxr genaal jrgonpx furznyr gbjryurnq wvtnobb "
    "cbepuzbaxrl enturnq mvccreurnq fcrnepuhpxre"
)

# Blocked as whole words only: substring matching would hit innocent
# words ("spic" in "conspicuous", "coon" in "raccoon", "gook" in
# "gobbledygook", "dyke" in "Vandyke").
_SLURS_WORD = _rot13(
    "snt sntf fcvp fcvpf pbba pbbaf tbbx tbbxf puvax puvaxf qlxr qlxrf "
    "qnexvr qnexl"
)

# Profanity, strict fields only. Substring tier ("cunt" does hit
# "Scunthorpe": accepted; these fields are short names and URLs) ...
_PROFANITY_ANY = _rot13(
    "shpx fuvg phag ovgpu chffl ohffl juber fyhg gjng wvmm cravf intvan "
    "oybjwbo qvyqb uvgyre"
)

# ... and whole-word tier ("cum" in "cucumber", "anal" in "analysis",
# "nazi" in "Ashkenazi", "rape" in "grape", "cock" in "Hancock").
_PROFANITY_WORD = _rot13(
    "pbpx pbpxf qvpx qvpxf phz nany nahf encr encrq encvfg ergneq "
    "ergneqrq anmv nff"
)


def _pattern(term: str) -> re.Pattern[str]:
    """Repeat-tolerant, mask-tolerant pattern for one term.

    Every letter accepts repeats ("niggger"); interior letters also accept
    the * wildcard ("n*gger"). First and last letters must be literal, and
    each interior run is capped at 3, so a long mask run can't collapse
    onto a short term (a self-censored "f******g" must not match the
    three-letter f-slur).
    """
    if len(term) <= 2:
        body = "".join(c + "+" for c in term)
    else:
        body = (
            term[0] + "+"
            + "".join(f"[{c}*]{{1,3}}" for c in term[1:-1])
            + term[-1] + "+"
        )
    return re.compile(body)


_SLURS_ANY_PATS = tuple(_pattern(t) for t in _SLURS_ANY)
_SLURS_WORD_PATS = tuple(_pattern(t) for t in _SLURS_WORD)
_PROFANITY_ANY_PATS = tuple(_pattern(t) for t in _PROFANITY_ANY)
_PROFANITY_WORD_PATS = tuple(_pattern(t) for t in _PROFANITY_WORD)


def _forms(text: str) -> tuple[str, list[str]]:
    """(squeezed, words): letters+masks only, casefolded, de-leeted."""
    t = unicodedata.normalize("NFKD", text).casefold()
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.translate(_LEET)
    words = [w for w in _SEP_RE.split(t) if w]
    return "".join(words), words


def contains_blocked(text: str, strict: bool = False) -> bool:
    """True if the text contains a blocked term.

    Non-strict blocks slurs only; ``strict=True`` also blocks profanity.
    """
    if not text:
        return False
    squeezed, words = _forms(text)
    if not squeezed:
        return False
    any_pats = _SLURS_ANY_PATS + (_PROFANITY_ANY_PATS if strict else ())
    word_pats = _SLURS_WORD_PATS + (_PROFANITY_WORD_PATS if strict else ())
    if any(p.search(squeezed) for p in any_pats):
        return True
    return any(p.fullmatch(w) for w in words for p in word_pats)
