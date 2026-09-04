# Filter Lists

Comprehensive blocklist for ads, privacy & annoyance filter list — auto-compiled from trusted sources into a single file.

## Subscribe

Add this **one URL** to your browser:

```
https://raw.githubusercontent.com/anT0ny54/filter-lists/refs/heads/main/filters.txt
```

### Supported
uBlock Origin, AdGuard, AdBlock Plus, and compatible blockers.

### Install
1. Open your blocker dashboard
2. Go to **Filter lists**
3. Import the URL above
4. Apply or save changes

## How It Works

This repository is updated automatically by GitHub Actions.

Workflow:
1. Downloads all sources from `sources.txt`
2. Resolves nested `!#include` directives
3. Validates downloads
4. Removes comments and duplicates
5. Appends rules from `custom-rules.txt`
6. Commits `filters.txt` only when changes are detected

## Configuration

- `sources.txt` — upstream source list
- `custom-rules.txt` — local custom rules
- GitHub Actions — manual rebuild trigger

#### :department_store: **My Free DNS Server — free** <a name="dns-server"></a>

Use HaGeZi Blocklists Multi Pro + TIF with [My Free DNS].

| Hagezi Blocklists | DNS-over-HTTPS |
| --- | --- |
| Multi Pro + TIF | `https://freedns-six.vercel.app/api/doh/dns-query` (Recommended) |
| Multi Pro + TIF | `https://dnssix.netlify.app/api/doh/dns-query` |

# ⚡ Bandwidth Hero Server

> A lightweight image proxy that cuts bandwidth and speeds up browsing.

Bandwidth Hero Server fetches remote images, compresses them, and returns optimized versions for faster loading and lower data use.

## Legal Disclaimer

- Personal use only
- No affiliation
- Third-party content only
- No distribution or recommendation
- No commercial use
- No intent to cause harm
- No warranty
- Compliance is the user’s responsibility

See [LICENSE](LICENSE) for full legal terms.

## Supporting My Project

If you'd like to support the project, donate:

- Bitcoin: `1HntwKxyqGCfnSGvGLMUTRAqLnTvLarAQP`
