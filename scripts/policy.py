#!/usr/bin/env python3
"""Compatibility policy for the Filter-Lists v6 build.

The existing strict ABP policy is intentionally preserved. This module makes
that policy explicit and reusable without changing the accepted rule profile.
"""
from __future__ import annotations

TYPE_OPTIONS = {
    "script", "image", "stylesheet", "object", "xmlhttprequest",
    "subdocument", "ping", "websocket", "webrtc", "document",
    "elemhide", "generichide", "genericblock", "popup", "font",
    "media", "other", "match-case",
}
INVERSE_OPTIONS = {f"~{x}" for x in {
    "script", "image", "stylesheet", "object", "xmlhttprequest",
    "subdocument", "ping", "websocket", "webrtc", "document",
    "elemhide", "other",
}}
SIMPLE_OPTIONS = {"third-party", "~third-party", "match-case"}
VALUE_OPTIONS = {"domain", "sitekey", "csp", "rewrite"}
REWRITE_RESOURCES = {
    "blank-text", "blank-css", "blank-js", "blank-html",
    "blank-mp3", "blank-mp4", "1x1-transparent-gif",
    "2x2-transparent-png", "3x2-transparent-png", "32x32-transparent-png",
}

PROFILE_NAME = "strict-abp"
PROFILE_DESCRIPTION = (
    "ABP external-list-safe core syntax; engine-specific uBO/AdGuard-only "
    "features are excluded."
)


def allowed_option_names() -> set[str]:
    return TYPE_OPTIONS | INVERSE_OPTIONS | SIMPLE_OPTIONS | VALUE_OPTIONS
