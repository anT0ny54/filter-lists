# Differential Engine Testing

The repository includes an optional differential-test harness. It has no mandatory runtime dependency on browser/filter engines.

## Adapter contract

Set an engine command using an environment variable such as `FILTER_ENGINE_CMD`. The command must accept an input file path through `{input}` and exit with status 0 when the input is accepted by that engine. Example:

```text
FILTER_ENGINE_CMD='my-engine --validate {input}' python3 scripts/differential.py
```

The harness tests the curated corpus and reports which fixtures an external engine accepts or rejects. This is deliberately opt-in because ABP, uBO, and AdGuard do not share a universal CLI interface.

CI can run the harness whenever a supported engine adapter is installed; otherwise the step is skipped rather than pretending that engine coverage exists.
