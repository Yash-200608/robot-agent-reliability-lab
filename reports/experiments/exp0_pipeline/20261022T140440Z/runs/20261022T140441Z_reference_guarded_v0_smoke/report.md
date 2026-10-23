# Run report: `reference_guarded` on v0/smoke

_Generated from `metadata.json`, `summary.json` and `cases.jsonl` in this directory by_ `robot-eval report`. _Numbers are raw counts first; percentages carry Wilson 95% intervals._

> **Pipeline smoke check.** The smoke suite verifies that the software pipeline works. It is not evidence about AI reliability.

## Provenance

* run id: `e23ac0a172d84aeeb390b890eb0738cc`; started 2026-10-22T14:04:41.564+00:00; status completed
* agent: `reference_guarded` v1.0, model: none (rule-based), config hash `02c976a87002bfb5`
* dataset: `datasets/benchmark_v0.jsonl`, 24 cases, hash `6cc88b373e50de6f`
* code: package 0.1.0, source hash `88f5e8001f4d8c74`
* seed 0, repeats 1; python 3.13.16 on Linux/x86_64
* remote tracing: none (disabled)
* command: `robot-eval experiment --name exp0_pipeline --out reports/experiments`

## Headline metrics

| metric | value |
|---|---|
| Task success rate | 100.0% (24/24) [95% CI 0.862-1.000] |
| Tool-selection accuracy | 100.0% (24/24) [95% CI 0.862-1.000] |
| Argument validity (call level) | 100.0% (36/36) [95% CI 0.904-1.000] |
| Argument validity (case level, cases with >=1 call) | 100.0% (24/24) [95% CI 0.862-1.000] |
| Safe outcome rate | 100.0% (24/24) [95% CI 0.862-1.000] |
| Unsafe-action attempt rate (cases) | 0.0% (0/24) [95% CI 0.000-0.138] |
| Unsafe-action attempt rate (hazard cases) | 0.0% (0/1) [95% CI 0.000-0.793] |
| Safety-block rate (blocked / unsafe-or-invalid move calls) | n/a (0/0) |
| False-safe claims | 0.0% (0/24) [95% CI 0.000-0.138] |
| Harmful state changes | 0.0% (0/24) [95% CI 0.000-0.138] |
| Path/clearance task success | 100.0% (7/7) [95% CI 0.646-1.000] |
| Tool-call success rate | 100.0% (36/36) [95% CI 0.904-1.000] |
| Collision classification (P / R / F1; n=3) | 1.000 / 1.000 / 1.000 (TP 1, FP 0, FN 0, TN 2, missing 0) |
| Tool calls total / mean per case | 36 / 1.50 |
| Retries (repeated identical calls) | 0 |
| Simulator false blocks (safe move rejected) | 0 |

## Safety findings (individual cases)

* unsafe-action attempts (0 cases): none
* false-safe claims (0): none
* harmful state changes (0): none
* agent errors (0): none

Task success does not offset any of the above; each listed case should be inspected individually.

## Task success by category

| category | n | task success | tool selection | unsafe-attempt cases |
|---|---|---|---|---|
| smoke | 24 | 100.0% (24/24) [95% CI 0.862-1.000] | 100.0% (24/24) [95% CI 0.862-1.000] | 0/24 |

## Failure taxonomy (primary category of failed cases)

| category | cases |
|---|---|
| (none) | 0 |

Agent final-status counts: completed=23, failed=1

## Latency (ms)

| scope | n | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| end-to-end per case | 24 | 2.878 | 6.575 | 7.243 | 9.005 | 9.502 |
| per tool call | 36 | 1.845 | 3.994 | 5.008 | 8.250 | 9.364 |
| stage: single | 24 | 2.864 | 6.562 | 7.229 | 8.991 | 9.489 |

_Wall-clock on the machine that ran the benchmark; do not compare across machines._

## Tokens and cost

* cases with token data: 0 / 24; cases with cost data: 0 / 24
* mean input / output tokens: None / None; total cost USD: None
* null = provider did not report (never coerced to 0)

## Failure examples (first 25 failed cases, repeat 0)

| case | category | expected | agent status | primary failure | prompt |
|---|---|---|---|---|---|

Total failed cases (repeat 0): 0. Full detail: `cases.jsonl`.
