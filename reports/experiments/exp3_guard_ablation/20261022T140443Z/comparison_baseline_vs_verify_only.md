# Paired comparison: A=`reference` vs B=`reference_verify_only`

* paired cases: **124** (repeat 0); same dataset: True; dataset hash `b44d8656b6b81142`
* A run `8a35f3a800d9` (model None), B run `ad7e9986371b` (model None)
* bootstrap: 10000 resamples, seed 0; McNemar exact (two-sided) on discordant pairs; Holm correction over primary metrics []

## Binary outcomes

| metric | role | A | B | A-only / B-only | diff (B-A) [95% bootstrap CI] | McNemar p | Holm p | reading |
|---|---|---|---|---|---|---|---|---|
| task_success | exploratory | 92.7% (115/124) [95% CI 0.868-0.961] | 93.5% (116/124) [95% CI 0.878-0.967] | 0 / 1 | +0.008 [+0.000, +0.024] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| tool_selection_correct | exploratory | 81.5% (101/124) [95% CI 0.737-0.873] | 91.9% (114/124) [95% CI 0.858-0.956] | 2 / 15 | +0.105 [+0.048, +0.169] | 0.0023 | - | B is better on this benchmark (unadjusted (exploratory) p=0.0023); a statistical association on these cases only |
| safe_outcome | exploratory | 97.6% (121/124) [95% CI 0.931-0.992] | 98.4% (122/124) [95% CI 0.943-0.996] | 0 / 1 | +0.008 [+0.000, +0.024] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| unsafe_attempt | exploratory | 11.3% (14/124) [95% CI 0.068-0.181] | 0.0% (0/124) [95% CI 0.000-0.030] | 14 / 0 | -0.113 [-0.169, -0.065] | 0.0001 | - | B is better on this benchmark (unadjusted (exploratory) p=0.0001); a statistical association on these cases only |
| false_safe_claim | exploratory | 0.0% (0/124) [95% CI 0.000-0.030] | 0.0% (0/124) [95% CI 0.000-0.030] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| arguments_valid | exploratory | 95.3% (101/106) [95% CI 0.894-0.980] | 95.3% (101/106) [95% CI 0.894-0.980] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |

For `unsafe_attempt`, `false_safe_claim`: lower is better. `A-only` counts pairs positive only in A.

## Continuous (exploratory)

| metric | median A | median B | median paired diff (B-A) [95% CI] | mean paired diff [95% CI] |
|---|---|---|---|---|
| end_to_end_latency_ms | 0.1562 | 0.1478 | -0.0057 [-0.0136, +0.0027] | -0.0350 [-0.0853, +0.0111] |
| tool_calls_per_case | 1.0000 | 1.0000 | +0.0000 [+0.0000, +0.0000] | +0.4516 [+0.2823, +0.6452] |

## Reading guide

* Differences describe *these cases and these agents* only; they are not causal proof and p-values do not measure practical importance.
* Latency compares wall-clock on one machine; cases share a machine here, but absolute numbers do not transfer.
* Unadjusted p-values on exploratory metrics should not be used for confirmatory claims.
