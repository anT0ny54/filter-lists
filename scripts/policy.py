#!/usr/bin/env python3
"""Compatibility policy for the Filter-Lists build.

The existing strict ABP policy is intentionally preserved. This module makes
that policy explicit and reusable without changing the accepted rule profile.
"""
from __future__ import annotations

# ABP request types. Every request type supports the `~` inverse modifier.
# The four exception-only options (document, elemhide, generichide, and
# genericblock) are deliberately kept separate: they are not request types and
# must never be accepted with `~`.
TYPE_OPTIONS = {
    "script", "image", "stylesheet", "object", "xmlhttprequest",
    "subdocument", "ping", "websocket", "webrtc", "font", "media",
    "popup", "other", "webbundle",
}
EXCEPTION_ONLY_OPTIONS = {"document", "elemhide", "generichide", "genericblock"}
INVERSE_OPTIONS = {f"~{x}" for x in TYPE_OPTIONS}
# match-case is a standalone modifier, not a resource type, so it belongs
# only in SIMPLE_OPTIONS (it was previously duplicated into TYPE_OPTIONS too).
SIMPLE_OPTIONS = {"third-party", "~third-party", "match-case"}
VALUE_OPTIONS = {"domain", "sitekey", "csp", "rewrite", "header", "addheader"}
REWRITE_RESOURCES = {
    "blank-text", "blank-css", "blank-js", "blank-html",
    "blank-mp3", "blank-mp4", "1x1-transparent-gif",
    "2x2-transparent-png", "3x2-transparent-png", "32x32-transparent-png",
}

PROFILE_NAME = "strict-abp"
PROFILE_DESCRIPTION = (
    "Strict Adblock Plus syntax, including current ABP network, content, "
    "header, addheader, snippet and snippet-exception, extended-CSS, "
    "inline-style, and remove "
    "features; uBO/AdGuard-only syntax remains excluded."
)
