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

## DNS Server

**My Free DNS Server**

Use **HaGeZi Blocklists Multi Pro + TIF** with:

- `https://freedns-six.vercel.app/api/doh/dns-query` — recommended
- `https://dnssix.netlify.app/api/doh/dns-query`

## Bandwidth Hero Server

A lightweight image optimization proxy designed to reduce bandwidth usage and speed up browsing.

Try it here: https://bhserv.netlify.app/

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

## Support

If you'd like to support the project:

- Bitcoin: `1HntwKxyqGCfnSGvGLMUTRAqLnTvLarAQP`
