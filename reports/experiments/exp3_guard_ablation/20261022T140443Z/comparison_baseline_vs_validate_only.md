# Paired comparison: A=`reference` vs B=`reference_validate_only`

* paired cases: **124** (repeat 0); same dataset: True; dataset hash `b44d8656b6b81142`
* A run `8a35f3a800d9` (model None), B run `9ad6c0c2863b` (model None)
* bootstrap: 10000 resamples, seed 0; McNemar exact (two-sided) on discordant pairs; Holm correction over primary metrics []

## Binary outcomes

| metric | role | A | B | A-only / B-only | diff (B-A) [95% bootstrap CI] | McNemar p | Holm p | reading |
|---|---|---|---|---|---|---|---|---|
| task_success | exploratory | 92.7% (115/124) [95% CI 0.868-0.961] | 92.7% (115/124) [95% CI 0.868-0.961] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| tool_selection_correct | exploratory | 81.5% (101/124) [95% CI 0.737-0.873] | 81.5% (101/124) [95% CI 0.737-0.873] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| safe_outcome | exploratory | 97.6% (121/124) [95% CI 0.931-0.992] | 97.6% (121/124) [95% CI 0.931-0.992] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| unsafe_attempt | exploratory | 11.3% (14/124) [95% CI 0.068-0.181] | 11.3% (14/124) [95% CI 0.068-0.181] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| false_safe_claim | exploratory | 0.0% (0/124) [95% CI 0.000-0.030] | 0.0% (0/124) [95% CI 0.000-0.030] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| arguments_valid | exploratory | 99.0% (101/102) [95% CI 0.947-0.998] | 99.0% (101/102) [95% CI 0.947-0.998] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |

For `unsafe_attempt`, `false_safe_claim`: lower is better. `A-only` counts pairs positive only in A.

## Continuous (exploratory)

| metric | median A | median B | median paired diff (B-A) [95% CI] | mean paired diff [95% CI] |
|---|---|---|---|---|
| end_to_end_latency_ms | 0.1562 | 0.0983 | -0.0495 [-0.0719, -0.0365] | -0.1175 [-0.1645, -0.0760] |
| tool_calls_per_case | 1.0000 | 1.0000 | +0.0000 [+0.0000, +0.0000] | -0.0323 [-0.0645, -0.0081] |

## Reading guide

* Differences describe *these cases and these agents* only; they are not causal proof and p-values do not measure practical importance.
* Latency compares wall-clock on one machine; cases share a machine here, but absolute numbers do not transfer.
* Unadjusted p-values on exploratory metrics should not be used for confirmatory claims.
