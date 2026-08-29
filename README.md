# Filter Lists

Comprehensive ads, privacy & annoyance filter list — auto-compiled from trusted sources into a single file.

## Subscribe

Add this **one URL** to your browser:

```
https://raw.githubusercontent.com/anT0ny54/filter-lists/refs/heads/main/filters.txt
```

### uBlock Origin, ABP and etc
1. Dashboard → Filter lists → Import → paste the URL above
2. Click "Apply changes"


#### :department_store: **MyKoyebDNSServer, free** <a name="dns server"></a>

On [KoyebDNS](https://koyeb.com) you can use HaGeZi Blocklists MultiPro+TIF.

| HaGeZi Blocklists | DNS-over-HTTPS |
| --- | --- |
| MultiPro + TIF | `https://flaky-liza-ant0ny54-00dc5eb8.koyeb.app/dns-query` |


## How It Works

A GitHub Action runs daily (fully automatic, zero manual work):
1. Downloads all sources from `sources.txt` (with 90s per-URL timeout)
2. Resolves `!#include` directives recursively (up to 3 levels deep)
3. Validates downloads (rejects HTML error pages, empty files, binary content)
4. Strips comments and headers
5. Deduplicates with `sort -u`
6. Appends custom rules from `custom-rules.txt`
7. Commits updated `filters.txt` only if content changed

## Customization

- **Add/remove sources**: Edit `sources.txt`
- **Add custom rules**: Edit `custom-rules.txt`
- **Force rebuild**: Actions → Update Filter List → Run workflow

## Legal Disclaimer

- **Personal use only** — maintained exclusively for the repository owner's personal browsing on personal devices. Not a product, not a service, not offered to the public.
- **No affiliation** — does not represent any employer, organization, or professional entity (past, present, or future).
- **Third-party content** — all filter rules originate from independent, publicly available open-source projects. All IP rights remain with their respective authors. No claim of authorship or owners[...]
- **No distribution or recommendation** — the owner does not encourage, recommend, or endorse use by any third party.
- **No commercial use** — generates no revenue, accepts no payments, serves no business purpose.
- **No intent to cause harm** — sole purpose is personal privacy and security. No intent to cause economic loss to any advertiser, publisher, or ad network.
- **Right to privacy** — personal content filtering is a recognized lawful exercise of individual privacy rights under GDPR (EU), DPDPA (India), CCPA (USA), PIPEDA (Canada), UK GDPR, nDSG (Switzerla[...]
- **No warranty** — provided "as-is" without warranties of any kind. Use at your own risk.
- **Compliance** — users are solely responsible for compliance with their local laws.

See [LICENSE](LICENSE) for comprehensive legal terms covering all jurisdictions.
