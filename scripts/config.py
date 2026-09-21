#!/usr/bin/env python3
"""Centralized build configuration loading and validation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REGISTRY = ROOT / "sources.yaml"
POLICY_FILE = ROOT / "policies.yaml"
CUSTOM_RULES = ROOT / "custom-rules.txt"

# Single source of truth for the builder version. merge.py, report.py,
# validate.py, and fetch.py's outbound User-Agent all import this instead of
# each keeping an independent copy, which previously let the string drift
# out of sync between modules on a version bump.
BUILDER_VERSION = "7.5.2"


def _strict_bool(value, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean")


def _strict_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def canonical_url(url: str) -> str:
    """Canonicalize URL identity for source de-duplication and include traversal."""
    p = urlsplit(url.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def valid_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return p.scheme in {"http", "https"} and bool(p.netloc) and not any(c.isspace() for c in url)
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
    result = int(value)
    if result <= 0:
        raise ValueError(f"policies.yaml: {name} must be > 0")
    return result


def _load_policy() -> dict:
    if not POLICY_FILE.is_file():
        raise FileNotFoundError(f"Missing policy file: {POLICY_FILE}")
    return yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=1)
def load_policy_limits() -> tuple[int, int, int, int, int, int]:
    """Return policy limits in one cached, single-source-of-truth tuple."""
    policy = _load_policy()
    limits = policy.get("limits", {})
    return (
        _positive_int(limits.get("max_rule_length", 100_000), "max_rule_length"),
        _positive_int(limits.get("max_include_depth", 5), "max_include_depth"),
        _positive_int(limits.get("max_download_bytes", 50 * 1024 * 1024), "max_download_bytes"),
        _positive_int(limits.get("max_total_download_bytes", 500 * 1024 * 1024), "max_total_download_bytes"),
        _positive_int(limits.get("max_total_sources", 500), "max_total_sources"),
        _positive_int(limits.get("total_timeout_seconds", 1800), "total_timeout_seconds"),
    )


def load_config() -> BuildConfig:
    if not SOURCE_REGISTRY.is_file():
        raise FileNotFoundError(f"Missing source registry: {SOURCE_REGISTRY}")
    policy = _load_policy()
    source_data = yaml.safe_load(SOURCE_REGISTRY.read_text(encoding="utf-8")) or {}
    raw_sources = source_data.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources.yaml: 'sources' must be a list")

    sources: list[Source] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"sources.yaml: source #{index + 1} is not an object")
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not valid_url(url):
            raise ValueError(f"sources.yaml: invalid source #{index + 1}: {name or url}")
        url = canonical_url(url)
        if url in seen:
            raise ValueError(f"sources.yaml: duplicate canonical URL: {url}")
        seen.add(url)
        enabled = _strict_bool(item.get("enabled", True), f"sources.yaml: source #{index + 1}.enabled")
        priority = _strict_int(item.get("priority", 999999), f"sources.yaml: source #{index + 1}.priority")
        required = _strict_bool(item.get("required", False), f"sources.yaml: source #{index + 1}.required")
        if required and not enabled:
            raise ValueError(f"sources.yaml: source #{index + 1} cannot be required and disabled")
        sources.append(Source(
            name=name,
            url=url,
            category=str(item.get("category", "uncategorized")),
            enabled=enabled,
            priority=priority,
            required=required,
        ))

    sources.sort(key=lambda s: (s.priority, s.name.casefold(), s.name, s.url))
    sources = [s for s in sources if s.enabled]

    health = policy.get("source_health", {})
    ratio = float(health.get("minimum_success_ratio", 0.50))
    if not 0 <= ratio <= 1:
        raise ValueError("policies.yaml: minimum_success_ratio must be between 0 and 1")

    limits = policy.get("limits", {})
    max_rule_length = _positive_int(limits.get("max_rule_length", 100_000), "max_rule_length")
    max_include_depth = _positive_int(limits.get("max_include_depth", 5), "max_include_depth")
    max_download_bytes = _positive_int(limits.get("max_download_bytes", 50 * 1024 * 1024), "max_download_bytes")
    max_total_download_bytes = _positive_int(limits.get("max_total_download_bytes", 500 * 1024 * 1024), "max_total_download_bytes")
    max_total_sources = _positive_int(limits.get("max_total_sources", 500), "max_total_sources")
    total_timeout = _positive_int(limits.get("total_timeout_seconds", 1800), "total_timeout_seconds")
    history = policy.get("history", {})
    if not isinstance(history, dict):
        raise ValueError("policies.yaml: history must be an object")
    history_retention = _positive_int(history.get("retention", 10), "history.retention")

    anomaly = policy.get("anomaly_detection", {})
    if not isinstance(anomaly, dict):
        raise ValueError("policies.yaml: anomaly_detection must be an object")
    anomaly_enabled = _strict_bool(anomaly.get("enabled", True), "policies.yaml: anomaly_detection.enabled")
    byte_change = float(anomaly.get("max_bytes_change_ratio", 0.75))
    rule_change = float(anomaly.get("max_rule_count_change_ratio", 0.75))
    rejection_change = float(anomaly.get("max_rejection_rate_change", 0.25))
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
        bool(health.get("fail_if_zero_sources", True)),
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
