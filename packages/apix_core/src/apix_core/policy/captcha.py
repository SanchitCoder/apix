"""Challenge detection.

If a source answers with a CAPTCHA or bot-management challenge, APIx stops collecting
from it. Detection exists so the stop is immediate, recorded and attributable — never
so the challenge can be answered. There is no solver in this codebase and none may be
added (CLAUDE.md guardrail).
"""

from __future__ import annotations

import re

# Signature name -> pattern over the raw response body. Names are stable identifiers:
# they end up in logs and in ``collection_run.error_detail``, so renaming one breaks
# the ability to group historical blocks.
_SIGNATURES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("recaptcha", re.compile(rb"www\.google\.com/recaptcha|class=[\"']g-recaptcha", re.I)),
    ("hcaptcha", re.compile(rb"hcaptcha\.com/1/api\.js|class=[\"']h-captcha", re.I)),
    (
        "cloudflare_challenge",
        re.compile(
            rb"challenges\.cloudflare\.com|cf_chl_|cf-challenge"
            rb"|Checking your browser before accessing",
            re.I,
        ),
    ),
    ("akamai_bot_manager", re.compile(rb"akam/1[0-9]/pixel|bm-verify", re.I)),
    ("perimeterx", re.compile(rb"px-captcha|/px/captcha|window\._pxAppId", re.I)),
    ("datadome", re.compile(rb"captcha-delivery\.com|geo\.captcha-delivery", re.I)),
    ("generic_captcha_page", re.compile(rb"<title>[^<]{0,80}captcha[^<]{0,80}</title>", re.I)),
)


def detect_challenge(body: bytes) -> str | None:
    """Return the name of the first matching challenge signature, or None.

    Matching is over raw bytes so a mislabelled or binary response cannot dodge
    detection by failing to decode.
    """
    for name, pattern in _SIGNATURES:
        if pattern.search(body):
            return name
    return None


__all__ = ["detect_challenge"]
