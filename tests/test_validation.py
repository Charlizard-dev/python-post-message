from __future__ import annotations

import pytest

from app.validation import extract_links, validate_message, validate_url

VALID = "Check out our latest business platform and grow your online visibility. https://example.com"


def test_valid_message_is_accepted_and_stripped():
    assert validate_message(f"  {VALID}  ") == VALID


def test_message_exactly_200_chars_is_accepted():
    url = "https://example.com"
    message = "a" * (200 - len(url) - 1) + " " + url
    assert len(message) == 200
    assert validate_message(message) == message


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("", "must not be empty"),
        ("   ", "must not be empty"),
        ("x" * 190 + " https://example.com", "must not exceed 200"),
        ("No link here at all", "none was found"),
        ("Two https://a.com and https://b.com", "found 2"),
        ("Mixed https://a.com and www.b.com", "found 2"),
        ("Go to www.example.com", "http:// or https://"),
        ("Try ftp://example.com/file", "http:// or https://"),
        ("Bad https://localhost:8000/x", "public domain"),
        ("Bad https://intranet/x", "public domain"),
        ("Bad https://192.168.1.10/x", "public address"),
        ("Bad https://127.0.0.1/x", "public address"),
        ("Bad https://user:pass@example.com", "credentials"),
        ("Bad https://exa_mple.com", "invalid domain"),
        ("Bad https://example.c0m", "invalid domain"),
        ("Bad https://example.com:99999", "not a valid URL"),
    ],
)
def test_invalid_messages_are_rejected(message, reason):
    with pytest.raises(ValueError, match=reason):
        validate_message(message)


def test_trailing_punctuation_is_not_part_of_the_link():
    assert extract_links("Visit https://example.com/path?q=1.") == ["https://example.com/path?q=1"]
    assert extract_links("(see https://example.com)") == ["https://example.com"]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://sub.example.co.uk/path?x=1#frag",
        "https://example.com:8443/a",
        "https://8.8.8.8/",
        "https://xn--bcher-kva.example",
    ],
)
def test_valid_urls(url):
    validate_url(url)
