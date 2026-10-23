# Paired comparison: A=`reference_guarded` vs B=`two_stage_rule`

* paired cases: **124** (repeat 0); same dataset: True; dataset hash `b44d8656b6b81142`
* A run `5a88563397ea` (model None), B run `a2c878d3a403` (model None)
* bootstrap: 10000 resamples, seed 0; McNemar exact (two-sided) on discordant pairs; Holm correction over primary metrics ['task_success', 'unsafe_attempt']

## Binary outcomes

| metric | role | A | B | A-only / B-only | diff (B-A) [95% bootstrap CI] | McNemar p | Holm p | reading |
|---|---|---|---|---|---|---|---|---|
| task_success | primary | 93.5% (116/124) [95% CI 0.878-0.967] | 96.8% (120/124) [95% CI 0.920-0.987] | 0 / 4 | +0.032 [+0.008, +0.065] | 0.1250 | 0.2500 | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| tool_selection_correct | exploratory | 92.7% (115/124) [95% CI 0.868-0.961] | 96.0% (119/124) [95% CI 0.909-0.983] | 0 / 4 | +0.032 [+0.008, +0.065] | 0.1250 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| safe_outcome | exploratory | 98.4% (122/124) [95% CI 0.943-0.996] | 100.0% (124/124) [95% CI 0.970-1.000] | 0 / 2 | +0.016 [+0.000, +0.040] | 0.5000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| unsafe_attempt | primary | 0.0% (0/124) [95% CI 0.000-0.030] | 0.0% (0/124) [95% CI 0.000-0.030] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | 1.0000 | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| false_safe_claim | exploratory | 0.0% (0/124) [95% CI 0.000-0.030] | 0.0% (0/124) [95% CI 0.000-0.030] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |
| arguments_valid | exploratory | 98.9% (92/93) [95% CI 0.942-0.998] | 98.9% (92/93) [95% CI 0.942-0.998] | 0 / 0 | +0.000 [+0.000, +0.000] | 1.0000 | - | inconclusive: fewer than 10 discordant pairs or 30 pairs; no significance claim is made |

For `unsafe_attempt`, `false_safe_claim`: lower is better. `A-only` counts pairs positive only in A.

## Continuous (exploratory)

| metric | median A | median B | median paired diff (B-A) [95% CI] | mean paired diff [95% CI] |
|---|---|---|---|---|
| end_to_end_latency_ms | 0.1575 | 0.1589 | +0.0058 [-0.0026, +0.0163] | -0.0240 [-0.0613, +0.0073] |
| tool_calls_per_case | 1.0000 | 1.0000 | +0.0000 [+0.0000, +0.0000] | -0.1290 [-0.2823, -0.0081] |

## Reading guide

* Differences describe *these cases and these agents* only; they are not causal proof and p-values do not measure practical importance.
* Latency compares wall-clock on one machine; cases share a machine here, but absolute numbers do not transfer.
* Unadjusted p-values on exploratory metrics should not be used for confirmatory claims.
