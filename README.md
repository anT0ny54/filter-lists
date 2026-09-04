# 🚀 Filter Lists

**Comprehensive blocklist for ads, privacy & annoyance** — auto-compiled from trusted sources into a single, powerful file.

---

## 📥 Subscribe

Add this **one URL** to your blocker:

```
https://raw.githubusercontent.com/anT0ny54/filter-lists/refs/heads/main/filters.txt
```

### 🛡️ Supported
uBlock Origin, AdGuard, AdBlock Plus, and compatible blockers.

### ⚙️ Installation
1. Open your blocker dashboard
2. Navigate to **Filter lists**
3. Import the URL above
4. Apply or save changes

---

## 🔧 How It Works

This repository updates automatically via GitHub Actions.

**Workflow:**
1. Downloads all sources from `sources.txt`
2. Resolves nested `!#include` directives
3. Validates downloads
4. Removes comments and duplicates
5. Appends rules from `custom-rules.txt`
6. Commits `filters.txt` only when changes detected

---

## ⚙️ Configuration

| File | Purpose |
| --- | --- |
| `sources.txt` | Upstream source list |
| `custom-rules.txt` | Local custom rules |
| GitHub Actions | Manual rebuild trigger |

---

## 🏪 My Free DNS Server

Use **HaGeZi Blocklists Multi Pro + TIF** with [My Free DNS].

| Service | DNS-over-HTTPS URL |
| --- | --- |
| Multi Pro + TIF (Recommended) | `https://freedns-six.vercel.app/api/doh/dns-query` |
| Multi Pro + TIF (Backup) | `https://dnssix.netlify.app/api/doh/dns-query` |

---

## ⚡ Bandwidth Hero Server

A lightweight image proxy that cuts bandwidth and speeds up browsing. Fetches remote images, compresses them, and returns optimized versions for faster loading and lower data use.

---

## ⚖️ Legal Notice

- **Personal use only**
- No official affiliation
- Third-party content only
- Not for distribution or commercial use
- No warranties provided
- User is responsible for compliance

See [LICENSE](LICENSE) for full legal terms.

---

## 💜 Support This Project

If you'd like to support development, consider donating:

**Bitcoin:** `1HntwKxyqGCfnSGvGLMUTRAqLnTvLarAQP`
