#!/usr/bin/env python3
"""Centralized V6 configuration loading and validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REGISTRY = ROOT / "sources.yaml"
LEGACY_SOURCES = ROOT / "sources.txt"
POLICY_FILE = ROOT / "policies.yaml"


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
    minimum_success_ratio: float = 0.50
    fail_if_zero_sources: bool = True
    max_rule_length: int = 100_000
    max_include_depth: int = 5
    max_download_bytes: int = 50 * 1024 * 1024
    total_timeout_seconds: int = 1800


def load_config() -> BuildConfig:
    if not SOURCE_REGISTRY.is_file():
        raise FileNotFoundError(f"Missing source registry: {SOURCE_REGISTRY}")
    if not POLICY_FILE.is_file():
        raise FileNotFoundError(f"Missing policy file: {POLICY_FILE}")
    source_data = yaml.safe_load(SOURCE_REGISTRY.read_text(encoding="utf-8")) or {}
    policy = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8")) or {}
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
        if url in seen:
            raise ValueError(f"sources.yaml: duplicate URL: {url}")
        seen.add(url)
        sources.append(Source(name, url, str(item.get("category", "uncategorized")), bool(item.get("enabled", True)), int(item.get("priority", 999999)), bool(item.get("required", False))))
    sources.sort(key=lambda s: (s.priority, s.name.casefold()))
    sources = [s for s in sources if s.enabled]
    limits = policy.get("limits", {})
    health = policy.get("source_health", {})
    ratio = float(health.get("minimum_success_ratio", 0.50))
    if not 0 <= ratio <= 1:
        raise ValueError("policies.yaml: minimum_success_ratio must be between 0 and 1")
    return BuildConfig(tuple(sources), ratio, bool(health.get("fail_if_zero_sources", True)), int(limits.get("max_rule_length", 100_000)), int(limits.get("max_include_depth", 5)), int(limits.get("max_download_bytes", 50 * 1024 * 1024)), int(limits.get("total_timeout_seconds", 1800)))


def load_legacy_urls() -> list[str]:
    if not LEGACY_SOURCES.is_file():
        return []
    return [x.strip() for x in LEGACY_SOURCES.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip() and not x.strip().startswith("#")]
