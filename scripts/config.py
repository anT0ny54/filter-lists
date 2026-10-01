#!/usr/bin/env python3
"""Centralized build configuration loading and validation."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

from policy import PROFILE_NAME

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REGISTRY = ROOT / "sources.yaml"
POLICY_FILE = ROOT / "policies.yaml"
CUSTOM_RULES = ROOT / "custom-rules.txt"

# Single source of truth for the builder version. merge.py, report.py,
# validate.py, and fetch.py's outbound User-Agent all import this instead of
# each keeping an independent copy, which previously let the string drift
# out of sync between modules on a version bump.
BUILDER_VERSION = "7.5.4"

# Schema revision of policies.yaml itself (its `version:` key).
POLICY_SCHEMA_VERSION = 3
# Fallback used when policies.yaml omits source_health.minimum_success_ratio.
# Kept equal to the shipped policies.yaml value so that deleting the key does
# not silently loosen the health gate.
DEFAULT_MINIMUM_SUCCESS_RATIO = 0.80
POLICY_TOP_LEVEL_KEYS = frozenset({
    "version", "profile", "rules", "limits", "history",
    "source_health", "anomaly_detection",
})
# Allowed keys inside each policies.yaml section. Unknown keys are rejected so
# a typo such as `max_bytes_change_ration` cannot silently fall back to the
# default and loosen a gate. (`rules` has its own table, RULE_POLICY_DEFAULTS.)
POLICY_SECTION_KEYS = {
    "limits": frozenset({
        "max_rule_length", "max_include_depth", "max_download_bytes",
        "max_total_download_bytes", "max_total_sources", "total_timeout_seconds",
    }),
    "history": frozenset({"retention"}),
    "source_health": frozenset({"minimum_success_ratio", "fail_if_zero_sources"}),
    "anomaly_detection": frozenset({
        "enabled", "max_bytes_change_ratio", "max_rule_count_change_ratio",
        "max_rejection_rate_change", "min_lines", "fail_on_warning",
    }),
}
SOURCES_TOP_LEVEL_KEYS = frozenset({"version", "sources"})
SOURCE_ITEM_KEYS = frozenset({"name", "url", "category", "enabled", "priority", "required", "trusted_abp_features"})


def _reject_unknown_keys(section: dict, allowed: frozenset, label: str) -> None:
    unknown = sorted(set(section) - allowed, key=str)
    if unknown:
        raise ValueError(f"{label}: unknown keys: {', '.join(map(str, unknown))}")


def _strict_bool(value, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean")


def _strict_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _strict_float(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def canonical_url(url: str) -> str:
    """Canonicalize URL identity for source de-duplication and include traversal.

    Default ports are removed so `https://example.com/a` and
    `https://example.com:443/a` have one canonical identity. Hostname and
    scheme case are normalized without retaining credentials or fragments.
    """
    p = urlsplit(url.strip())
    scheme = p.scheme.lower()
    hostname = p.hostname.lower() if p.hostname else ""
    try:
        port = p.port
    except ValueError:
        port = None
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if port == {"http": 80, "https": 443}.get(scheme):
        port = None
    netloc = hostname if port is None else f"{hostname}:{port}"
    return urlunsplit((scheme, netloc, p.path or "/", p.query, ""))


def valid_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme not in {"http", "https"} or not p.netloc or not p.hostname:
            return False
        # Source/redirect URLs are written to logs and reports. Reject
        # userinfo so credentials can never be accidentally exposed there.
        if p.username is not None or p.password is not None:
            return False
        # Force URL port parsing here so malformed ports fail configuration
        # validation instead of surfacing later during a network fetch.
        _ = p.port
        # An explicit trailing colon is an empty port, not an omitted port.
        if p.netloc.endswith(":"):
            return False
        return not any(c.isspace() for c in url)
    except ValueError:
        return False


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    category: str = "uncategorized"
    enabled: bool = True
    priority: int = 999999
    required: bool = False
    trusted_abp_features: bool = False


@dataclass(frozen=True)
class BuildConfig:
    sources: tuple[Source, ...]
    minimum_success_ratio: float
    fail_if_zero_sources: bool
    max_rule_length: int
    max_include_depth: int
    max_download_bytes: int
    max_total_download_bytes: int
    max_total_sources: int
    total_timeout_seconds: int
    anomaly_detection: dict
    history_retention: int


def _positive_int(value: object, name: str) -> int:
    result = _strict_int(value, f"policies.yaml: {name}")
    if result <= 0:
        raise ValueError(f"policies.yaml: {name} must be > 0")
    return result


def _policy_limits(policy: dict) -> tuple[int, int, int, int, int, int]:
    limits = policy.get("limits", {})
    if not isinstance(limits, dict):
        raise ValueError("policies.yaml: limits must be an object")
    _reject_unknown_keys(limits, POLICY_SECTION_KEYS["limits"], "policies.yaml: limits")
    return (
        _positive_int(limits.get("max_rule_length", 100_000), "max_rule_length"),
        _positive_int(limits.get("max_include_depth", 5), "max_include_depth"),
        _positive_int(limits.get("max_download_bytes", 50 * 1024 * 1024), "max_download_bytes"),
        _positive_int(limits.get("max_total_download_bytes", 500 * 1024 * 1024), "max_total_download_bytes"),
        _positive_int(limits.get("max_total_sources", 500), "max_total_sources"),
        _positive_int(limits.get("total_timeout_seconds", 1800), "total_timeout_seconds"),
    )


RULE_POLICY_DEFAULTS = {
    "allow_network_filters": True,
    "allow_abp_cosmetic": True,
    "allow_extended_css": True,
    "reject_ubo_procedural": True,
    "reject_ubo_extended_exceptions": True,
    "reject_hosts_format": True,
    "reject_html_error_pages": True,
    "reject_unknown_options": True,
    "reject_duplicate_options": True,
    "require_domain_for_rewrite": True,
    "allow_abp_header": True,
    "allow_abp_addheader": True,
    "allow_abp_snippets": True,
    "allow_abp_inline_styles": True,
    "allow_abp_remove_action": True,
}


def _load_policy() -> dict:
    if not POLICY_FILE.is_file():
        raise FileNotFoundError(f"Missing policy file: {POLICY_FILE}")
    data = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("policies.yaml: top level must be an object")
    # Reject unknown top-level keys so a typo (or a stale, never-read key)
    # cannot sit in the file looking like it has an effect.
    unknown = sorted(set(data) - POLICY_TOP_LEVEL_KEYS, key=str)
    if unknown:
        raise ValueError(f"policies.yaml: unknown top-level keys: {', '.join(map(str, unknown))}")
    if "version" in data and data["version"] != POLICY_SCHEMA_VERSION:
        raise ValueError(
            f"policies.yaml: unsupported version {data['version']!r} (expected {POLICY_SCHEMA_VERSION})"
        )
    if "profile" in data and data["profile"] != PROFILE_NAME:
        raise ValueError(
            f"policies.yaml: unsupported profile {data['profile']!r} (this builder implements {PROFILE_NAME!r})"
        )
    return data


@lru_cache(maxsize=1)
def load_policy_limits() -> tuple[int, int, int, int, int, int]:
    """Return policy limits in one cached, single-source-of-truth tuple."""
    return _policy_limits(_load_policy())


@lru_cache(maxsize=1)
def load_rule_policy() -> dict[str, bool]:
    """Load rule-processing switches that control normalization."""
    policy = _load_policy()
    rules = policy.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("policies.yaml: rules must be an object")
    unknown = sorted(set(rules) - set(RULE_POLICY_DEFAULTS))
    if unknown:
        raise ValueError(f"policies.yaml: unknown rule policies: {', '.join(unknown)}")
    return {
        key: _strict_bool(rules.get(key, default), f"policies.yaml: rules.{key}")
        for key, default in RULE_POLICY_DEFAULTS.items()
    }


def load_config() -> BuildConfig:
    if not SOURCE_REGISTRY.is_file():
        raise FileNotFoundError(f"Missing source registry: {SOURCE_REGISTRY}")
    policy = _load_policy()
    source_data = yaml.safe_load(SOURCE_REGISTRY.read_text(encoding="utf-8")) or {}
    if not isinstance(source_data, dict):
        raise ValueError("sources.yaml: top level must be an object")
    _reject_unknown_keys(source_data, SOURCES_TOP_LEVEL_KEYS, "sources.yaml")
    raw_sources = source_data.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources.yaml: 'sources' must be a list")

    sources: list[Source] = []
    seen: set[str] = set()
    seen_names: set[str] = set()
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"sources.yaml: source #{index + 1} is not an object")
        # A misspelled `required`/`enabled` would otherwise be ignored and
        # silently turn a health gate off.
        _reject_unknown_keys(item, SOURCE_ITEM_KEYS, f"sources.yaml: source #{index + 1}")
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not valid_url(url):
            raise ValueError(f"sources.yaml: invalid source #{index + 1}: {name or url}")
        url = canonical_url(url)
        if url in seen:
            raise ValueError(f"sources.yaml: duplicate canonical URL: {url}")
        name_key = name.casefold()
        if name_key in seen_names:
            raise ValueError(f"sources.yaml: duplicate source name: {name}")
        seen_names.add(name_key)
        seen.add(url)
        enabled = _strict_bool(item.get("enabled", True), f"sources.yaml: source #{index + 1}.enabled")
        priority = _strict_int(item.get("priority", 999999), f"sources.yaml: source #{index + 1}.priority")
        required = _strict_bool(item.get("required", False), f"sources.yaml: source #{index + 1}.required")
        trusted = _strict_bool(
            item.get("trusted_abp_features", False),
            f"sources.yaml: source #{index + 1}.trusted_abp_features",
        )
        if required and not enabled:
            raise ValueError(f"sources.yaml: source #{index + 1} cannot be required and disabled")
        sources.append(Source(
            name=name,
            url=url,
            category=str(item.get("category", "uncategorized")),
            enabled=enabled,
            priority=priority,
            required=required,
            trusted_abp_features=trusted,
        ))

    sources.sort(key=lambda s: (s.priority, s.name.casefold(), s.name, s.url))
    sources = [s for s in sources if s.enabled]

    health = policy.get("source_health", {})
    if not isinstance(health, dict):
        raise ValueError("policies.yaml: source_health must be an object")
    _reject_unknown_keys(health, POLICY_SECTION_KEYS["source_health"], "policies.yaml: source_health")
    ratio = _strict_float(health.get("minimum_success_ratio", DEFAULT_MINIMUM_SUCCESS_RATIO), "policies.yaml: minimum_success_ratio")
    if not 0 <= ratio <= 1:
        raise ValueError("policies.yaml: minimum_success_ratio must be between 0 and 1")

    max_rule_length, max_include_depth, max_download_bytes, max_total_download_bytes, max_total_sources, total_timeout = _policy_limits(policy)
    history = policy.get("history", {})
    if not isinstance(history, dict):
        raise ValueError("policies.yaml: history must be an object")
    _reject_unknown_keys(history, POLICY_SECTION_KEYS["history"], "policies.yaml: history")
    history_retention = _positive_int(history.get("retention", 10), "history.retention")

    anomaly = policy.get("anomaly_detection", {})
    if not isinstance(anomaly, dict):
        raise ValueError("policies.yaml: anomaly_detection must be an object")
    _reject_unknown_keys(anomaly, POLICY_SECTION_KEYS["anomaly_detection"], "policies.yaml: anomaly_detection")
    anomaly_enabled = _strict_bool(anomaly.get("enabled", True), "policies.yaml: anomaly_detection.enabled")
    byte_change = _strict_float(anomaly.get("max_bytes_change_ratio", 0.75), "policies.yaml: max_bytes_change_ratio")
    rule_change = _strict_float(anomaly.get("max_rule_count_change_ratio", 0.75), "policies.yaml: max_rule_count_change_ratio")
    rejection_change = _strict_float(anomaly.get("max_rejection_rate_change", 0.25), "policies.yaml: max_rejection_rate_change")
    if not 0 <= byte_change <= 10 or not 0 <= rule_change <= 10 or not 0 <= rejection_change <= 1:
        raise ValueError("policies.yaml: invalid anomaly thresholds")
    anomaly_config = {
        "enabled": anomaly_enabled,
        "max_bytes_change_ratio": byte_change,
        "max_rule_count_change_ratio": rule_change,
        "max_rejection_rate_change": rejection_change,
        "min_lines": _positive_int(anomaly.get("min_lines", 100), "anomaly_detection.min_lines"),
        "fail_on_warning": _strict_bool(anomaly.get("fail_on_warning", False), "policies.yaml: anomaly_detection.fail_on_warning"),
    }
    return BuildConfig(
        tuple(sources),
        ratio,
        _strict_bool(health.get("fail_if_zero_sources", True), "policies.yaml: source_health.fail_if_zero_sources"),
        max_rule_length,
        max_include_depth,
        max_download_bytes,
        max_total_download_bytes,
        max_total_sources,
        total_timeout,
        anomaly_config,
        history_retention,
    )


def sha256_file(path: Path) -> str:
    """Stream-hash a file. Single shared implementation for fetch/merge/report."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_source_manifest(digest, config: BuildConfig) -> None:
    """Feed the ordered (name, url, category, priority, required) source manifest into `digest`."""
    for source in config.sources:
        digest.update(f"{source.name}\0{source.url}\0{source.category}\0{source.priority}\0{source.required}\n".encode())


def source_manifest_sha256(config: BuildConfig) -> str:
    """Hash the ordered source manifest.

    Shared by the builder (to publish the manifest hash) and the validator
    (to confirm a generated list matches its declared sources.yaml).
    """
    h = hashlib.sha256()
    _hash_source_manifest(h, config)
    return h.hexdigest()


def config_fingerprint(config: BuildConfig) -> str:
    """Hash the source manifest plus policy/custom-rules content for the Build-ID."""
    h = hashlib.sha256()
    _hash_source_manifest(h, config)
    for path in (POLICY_FILE, CUSTOM_RULES):
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()
