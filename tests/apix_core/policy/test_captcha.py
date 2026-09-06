"""Challenge detection: recognised, named, and never solved."""

from __future__ import annotations

import pytest

from apix_core.policy.captcha import detect_challenge


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b'<script src="https://www.google.com/recaptcha/api.js"></script>', "recaptcha"),
        (b'<div class="g-recaptcha" data-sitekey="k"></div>', "recaptcha"),
        (b'<script src="https://hcaptcha.com/1/api.js" async defer></script>', "hcaptcha"),
        (b'<div class="h-captcha" data-sitekey="k"></div>', "hcaptcha"),
        (
            b'<iframe src="https://challenges.cloudflare.com/turnstile"></iframe>',
            "cloudflare_challenge",
        ),
        (b"<title>Just a moment...</title>window._cf_chl_opt", "cloudflare_challenge"),
        (b"Checking your browser before accessing example.test", "cloudflare_challenge"),
        (b'<input type="hidden" name="bm-verify" value="x">', "akamai_bot_manager"),
        (b'<div id="px-captcha"></div>', "perimeterx"),
        (b'<script src="https://geo.captcha-delivery.com/captcha/"></script>', "datadome"),
        (b"<html><head><title>CAPTCHA required</title></head></html>", "generic_captcha_page"),
    ],
)
def test_known_challenge_signatures_are_detected(body, expected):
    assert detect_challenge(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>DEL-BOM economy 4999 INR</body></html>",
        b'{"fares": [{"total": 4999, "currency": "INR"}]}',
        b"",
        # Prose about captchas is not a challenge page.
        b"<p>Our accessibility statement covers captcha alternatives.</p>",
        b"\x89PNG\r\n\x1a\n binary junk",
    ],
)
def test_ordinary_responses_are_not_flagged(body):
    assert detect_challenge(body) is None


def test_there_is_no_solver_in_the_policy_package():
    """CLAUDE.md guardrail: detection exists to stop, never to answer."""
    import importlib

    import apix_core.policy as policy

    names = set(dir(policy))
    for module_name in ("captcha", "decisions", "engine", "errors", "ratelimit", "robots"):
        names |= set(dir(importlib.import_module(f"apix_core.policy.{module_name}")))
    assert not any("solve" in name.lower() or "bypass" in name.lower() for name in names)
