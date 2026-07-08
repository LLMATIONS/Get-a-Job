"""Self-contained checks for the content screen. Run: python3 server/test_moderation.py

Offensive fixtures are ROT13-encoded (same convention as the module) so
this file stays grep-clean; ``_r`` decodes them at test time.
"""
import codecs

from moderation import contains_blocked


def _r(s: str) -> str:
    return codecs.decode(s, "rot13")


BLOCKED_EVERYWHERE = [
    _r("avttre"),                      # plain slur
    _r("AvttreSnttbg"),                # the drive-by from 2026-07-07, cased
    _r("a1ttre"),                      # leetspeak digit
    _r("a v t t r e"),                 # spaced out
    _r("a.v-t_t.r/e"),                 # separator-stuffed
    _r("avtttttre"),                   # letter stuffing
    _r("a*ttre"),                      # masked vowel
    _r("s#ttbg shel"),                 # masked + trailing word
    _r("snttbg") + " druid",           # slur inside a class string
    "what a " + _r("fcvp"),            # word-tier slur, standalone word
    _r("genaal"),                      # any-tier slur
]

ALLOWED_EVERYWHERE = [
    "",
    "Resto Druid",
    "cleared Kara and Gruul pre-nerf, MT for SSC",
    "I fucking love raiding",          # profanity is fine in paragraphs
    "f******g love this game",         # self-censored profanity != slur
    "conspicuous raccoon gobbledygook",  # word-tier terms inside words
    "my cousin from Nigeria",          # single g: must not match the double-g slur
    "analysis of the therapist from Ashkenazi history",
    "grape drapes on Uranus",
    "assess the assassin's cuisine",
    "Vandyke the classy Hancock",
]

BLOCKED_STRICT_ONLY = [
    "HTTPS://FUCKMYLILBOIBUSSY.NET",   # the drive-by's logs "URL"
    "b1tch",
    "Sh!tlord",
    "c**k",                            # masked word-tier profanity
    "Scunthorpe",                      # accepted false positive, pinned here
    "Hitlerfan",
]

ALLOWED_STRICT = [
    "Ivorycrayon",
    "Feral Druid",
    "https://fresh.warcraftlogs.com/guild/id/828086",
    "Assassin",                        # word-tier "ass" must not hit substrings
    "Peacock",
    "Classy",
    "6969",
    "Cocktail",
]


def main() -> None:
    for s in BLOCKED_EVERYWHERE:
        assert contains_blocked(s), f"should block everywhere: {s!r}"
        assert contains_blocked(s, strict=True), f"should block strict: {s!r}"
    for s in ALLOWED_EVERYWHERE:
        assert not contains_blocked(s), f"should allow non-strict: {s!r}"
    for s in BLOCKED_STRICT_ONLY:
        assert contains_blocked(s, strict=True), f"should block strict: {s!r}"
        assert not contains_blocked(s), f"should allow non-strict: {s!r}"
    for s in ALLOWED_STRICT:
        assert not contains_blocked(s, strict=True), f"should allow strict: {s!r}"
    total = (
        len(BLOCKED_EVERYWHERE) + len(ALLOWED_EVERYWHERE)
        + len(BLOCKED_STRICT_ONLY) + len(ALLOWED_STRICT)
    )
    print(f"ok: {total} cases")


if __name__ == "__main__":
    main()
