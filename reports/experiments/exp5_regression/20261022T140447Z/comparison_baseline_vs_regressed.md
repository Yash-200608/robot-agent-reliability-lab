# Paired comparison: A=`reference` vs B=`reference_regressed`

* paired cases: **164** (repeat 0); same dataset: True; dataset hash `64810e1ba99d5813`
* A run `75f650eb5ae3` (model None), B run `dba2fba95f7c` (model None)
* bootstrap: 10000 resamples, seed 0; McNemar exact (two-sided) on discordant pairs; Holm correction over primary metrics ['task_success']

## Binary outcomes

| metric | role | A | B | A-only / B-only | diff (B-A) [95% bootstrap CI] | McNemar p | Holm p | reading |
|---|---|---|---|---|---|---|---|---|
| task_success | primary | 91.5% (150/164) [95% CI 0.862-0.948] | 83.5% (137/164) [95% CI 0.771-0.884] | 14 / 1 | -0.079 [-0.128, -0.037] | 0.0010 | 0.0010 | A is better on this benchmark (Holm-adjusted p=0.0010); a statistical association on these cases only |
| tool_selection_correct | exploratory | 79.9% (131/164) [95% CI 0.731-0.853] | 72.0% (118/164) [95% CI 0.646-0.783] | 14 / 1 | -0.079 [-0.128, -0.037] | 0.0010 | - | A is better on this benchmark (unadjusted (exploratory) p=0.0010); a statistical association on these cases only |
| safe_outcome | exploratory | 97.0% (159/164) [95% CI 0.931-0.987] | 97.0% (159/164) [95% CI 0.931-0.987] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| unsafe_attempt | exploratory | 12.8% (21/164) [95% CI 0.085-0.188] | 12.8% (21/164) [95% CI 0.085-0.188] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| false_safe_claim | exploratory | 0.6% (1/164) [95% CI 0.001-0.034] | 0.6% (1/164) [95% CI 0.001-0.034] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| arguments_valid | exploratory | 95.1% (135/142) [95% CI 0.902-0.976] | 95.1% (135/142) [95% CI 0.902-0.976] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |

For `unsafe_attempt`, `false_safe_claim`: lower is better. `A-only` counts pairs positive only in A.

## Continuous (exploratory)

| metric | median A | median B | median paired diff (B-A) [95% CI] | mean paired diff [95% CI] |
|---|---|---|---|---|
| end_to_end_latency_ms | 0.1448 | 0.1043 | -0.0409 [-0.0477, -0.0354] | -0.0832 [-0.1133, -0.0584] |
| tool_calls_per_case | 1.0000 | 1.0000 | +0.0000 [+0.0000, +0.0000] | -0.0061 [-0.0183, +0.0000] |

## Reading guide

* Differences describe *these cases and these agents* only; they are not causal proof and p-values do not measure practical importance.
* Latency compares wall-clock on one machine; cases share a machine here, but absolute numbers do not transfer.
* Unadjusted p-values on exploratory metrics should not be used for confirmatory claims.
