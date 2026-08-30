#!/usr/bin/env python3
"""
check_and_report.py

Check reachability of sources in sources.txt or sources.yaml and produce a JSON report.

Usage:
  pip install requests tqdm pyyaml
  python check_and_report.py --sources sources.txt --out report.json

Outputs report.json with entries:
  - url
  - status: ok | unreachable | error
  - http_status (if available)
  - final_url (after redirects)
  - content_type (if available)
  - reason (error message or HTTP status)

Optional:
  --to-yaml : generate sources.yaml from sources.txt before checking
  --sample   : only check first N urls (for quicker runs)
  --failures-only : only write failures to report

This script is intended to be run locally (it performs network requests). After you run it, paste the report here and I will prepare a PR to edit sources.txt / sources.yaml (replace dead URLs, or set enabled: false).
"""
import argparse
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_TIMEOUT = 10
RETRIES = 2
BACKOFF = 0.3


def read_sources_txt(path: Path) -> List[str]:
    urls = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            urls.append(s)
    # dedupe while preserving order
    seen = set()
    out = []
    for u in urls:
        if u in seen:
            logging.warning("Duplicate URL skipped: %s", u)
            continue
        seen.add(u)
        out.append(u)
    return out


def read_sources_yaml(path: Path) -> List[Dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("sources", [])


def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=RETRIES,
        backoff_factor=BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s


def check_url(session: requests.Session, url: str, timeout: int) -> Dict:
    out: Dict = {"url": url}
    try:
        # try HEAD first
        r = session.head(url, timeout=timeout, allow_redirects=True)
        # if HEAD seems blocked or returned non-2xx, use GET as fallback
        if r.status_code >= 400 or r.headers.get("content-type", "").startswith("text/html"):
            r = session.get(url, timeout=timeout, stream=True)
        out["http_status"] = r.status_code
        out["final_url"] = r.url
        out["content_type"] = r.headers.get("content-type")
        if 200 <= r.status_code < 400:
            out["status"] = "ok"
            out["reason"] = None
        else:
            out["status"] = "unreachable"
            out["reason"] = f"HTTP {r.status_code}"
    except Exception as e:
        out["status"] = "error"
        out["http_status"] = None
        out["final_url"] = None
        out["content_type"] = None
        out["reason"] = str(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, help="sources.txt or sources.yaml")
    ap.add_argument("--out", default="report.json", help="Output JSON report")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--to-yaml", action="store_true", help="Generate sources.yaml from sources.txt before checking")
    ap.add_argument("--sample", type=int, default=0, help="Only check first N URLs")
    ap.add_argument("--failures-only", action="store_true", help="Only include failures in the output report")
    args = ap.parse_args()

    src_path = Path(args.sources)
    if not src_path.exists():
        logging.error("Sources file not found: %s", src_path)
        return

    urls: List[str] = []
    if src_path.suffix.lower() in (".yaml", ".yml"):
        data = read_sources_yaml(src_path)
        for item in data:
            if isinstance(item, dict):
                url = item.get("url")
                enabled = item.get("enabled", True)
                if url and enabled:
                    urls.append(url)
    else:
        urls = read_sources_txt(src_path)
        if args.to_yaml:
            # generate a basic sources.yaml
            data = {"sources": [{"url": u, "enabled": True} for u in urls]}
            Path("sources.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            logging.info("Wrote sources.yaml")

    if args.sample > 0:
        urls = urls[: args.sample]

    logging.info("Checking %d URLs", len(urls))
    session = make_session()
    results = []
    for u in tqdm(urls, desc="Checking"):
        res = check_url(session, u, args.timeout)
        results.append(res)

    if args.failures_only:
        results = [r for r in results if r.get("status") != "ok"]

    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info("Wrote report: %s (entries: %d)", args.out, len(results))
    logging.info("Next: paste the report here and I will prepare a PR to update sources.txt/sources.yaml")


if __name__ == "__main__":
    main()
