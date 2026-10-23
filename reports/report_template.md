# <Title> - <agent(s)> on <dataset version/split>

_Template. Fill every section from saved artifacts (`outputs/runs/...` or `reports/experiments/...`); do not
include any number that is not traceable to a `cases.jsonl` / `summary.json` file. Delete this note._

## Abstract
One paragraph: what was evaluated (agents, model ids, dataset hash, date), the primary outcome with
numerator/denominator and 95% interval, and the main caveat. State plainly if a result is inconclusive.

## Questions
Which of RQ1-RQ4 (docs/experiment_protocol.md) this report addresses, and whether each comparison is
confirmatory or exploratory.

## Methods
* Agents and configurations (config hashes), model id/provider/prompt version for LLM arms, seeds, repeats, budgets.
* Dataset: file, version, hash, split, number of cases; held-out access disclosure.
* Metrics: link to docs/metric_definitions.md; statistical methods and multiplicity handling.
* Exact commands to reproduce.

## Results
Headline table (all component metrics with num/den and intervals - no single overall score), paired
comparison table (A-only/B-only counts, difference with bootstrap CI, McNemar p, Holm-adjusted p for primary
metrics), latency percentiles with n, tokens/cost where reported (else "not available").

## Failure analysis
Failure taxonomy counts; every unsafe-action attempt, false-safe claim and harmful state change listed by case id
with a sentence on the cause; representative failed prompts per category.

## Limitations
Simulation scope, dataset provenance (same author), synthetic language, sample size/power, provider
nondeterminism, anything skipped or blocked.

## Conclusion
What the evidence supports, weakens or leaves unresolved for each question - no claim beyond the pre-stated rules.
