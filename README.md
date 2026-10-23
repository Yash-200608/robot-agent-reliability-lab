# Robotics Agent Reliability Lab

A **simulation-only**, CPU-only evaluation lab that measures how reliably AI agents interpret requests, choose
robotics-style tools, produce valid arguments, respect safety constraints and finish simulated tasks - and how
that reliability changes with guards, orchestration and code changes.

> **Safety and scope.** Everything is a 2-D simulation. Nothing connects to a real robot, PLC or industrial system,
> and **no result here supports a claim of industrial safety, certification or readiness**. See
> [`docs/limitations_and_safety.md`](docs/limitations_and_safety.md).
>
> **Smoke check vs evaluation.** `datasets/benchmark_v0.jsonl` (24 cases) only proves the *software pipeline* works.
> It is not evidence about AI reliability. Evaluation uses `datasets/v1/` (288 cases) with a development / held-out split.
>
> **Provenance.** This repository was built from scratch (the originally described repository was unavailable); its
> v0 suite is newly authored. See [`docs/gate0_audit.md`](docs/gate0_audit.md).
>
> **No LLM results.** The LLM adapter exists and is tested offline, but was never run against a live API (no
> credentials in the build environment). All reported numbers are from deterministic rule-based agents.

## Install (CPU only, no accounts, no API keys)

Python >= 3.11 (tested on 3.13.16, Linux only; Windows is untested).

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # core + test tools
# optional extras:  pip install -e ".[mcp]"  /  ".[llm]"  /  ".[tracing]"  /  ".[all]"
```

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If `robot-eval` is not on your PATH, use `python -m robot_eval ...` instead.
Moving to your own computer (unzip, verify, line-ending caveat): [`docs/local_setup.md`](docs/local_setup.md).

## Quick start

```bash
robot-eval validate-dataset --dataset datasets/benchmark_v0.jsonl datasets/v1/development.jsonl datasets/v1/heldout_test.jsonl
robot-eval run --dataset datasets/benchmark_v0.jsonl --agent reference             # smoke check
robot-eval run --dataset datasets/v1/development.jsonl --agent reference          # iterate here
robot-eval run --dataset datasets/v1/development.jsonl --agent reference_guarded
robot-eval compare --runs outputs/runs/<run-a> outputs/runs/<run-b>               # paired comparison
robot-eval report  --run outputs/runs/<run> --verify                              # recompute summary from raw cases
robot-eval audit-dataset --dataset datasets/v1/development.jsonl datasets/v1/heldout_test.jsonl --out reports/audit
robot-eval regression-check --baseline reports/baselines/reference_development.summary.json --candidate outputs/runs/<run>
robot-eval list-agents
```

Real output of the smoke run (`robot-eval run --dataset datasets/benchmark_v0.jsonl --agent reference`):

```text
run directory: outputs/runs/20261022T140248Z_reference_v0_smoke
  task success      : 100.0% (24/24) [95% CI 0.862-1.000]
  tool selection    : 95.8% (23/24) [95% CI 0.798-0.993]
  safe outcome      : 100.0% (24/24) [95% CI 0.862-1.000]
  unsafe attempts   : 1/24 cases
  false-safe claims : 0/24 cases
```

(The one tool-selection miss is the unguarded agent *attempting* a move into an obstacle; the simulator blocked it.)

Each run writes a never-overwritten directory `outputs/runs/<UTC time>_<agent>_<version>_<split>/` with
`metadata.json` (dataset/config/source hashes, versions), `cases.jsonl` (raw per-case records), `events.jsonl`,
`summary.json` and `report.md`.

Exit codes: `0` ok; `1` a check failed (invalid dataset, regression found, verification mismatch); `2` usage/config
error; `3` an optional feature is unavailable (e.g. no LLM credentials) - then nothing is run and nothing is invented.

### Differences from the plan's example commands
Agents are selected by configured name (`--agent llm_single` / `llm_two_stage` rather than `--agent llm`), `--config`
defaults to `configs/agents.yaml`, and `audit-dataset` / `validate-dataset` accept several `--dataset` files.

## What is in the box

| piece | where |
|---|---|
| Deterministic 2-D workcell (5 worlds, circular obstacles, reach band, joint limits), 11 typed tools | `src/robot_eval/simulator`, `tools` - examples in [`docs/tools.md`](docs/tools.md) |
| **Independent exact-arithmetic oracle** (Fractions, no sqrt, no shared geometry code) | `evaluation/oracle.py`, `groundtruth.py` |
| Benchmark v0 (24 smoke) and v1 (288: 164 dev + 124 held-out, 17 categories), seeded generator, validator, audit | `datasets/`, `evaluation/{generator,dataset,audit}.py`, [`docs/benchmark_design.md`](docs/benchmark_design.md) |
| Agents on one interface: reference (A), fault-injection fixtures (B), guarded variants, rule two-stage (D), optional LLM (C/D) | `src/robot_eval/agents` |
| Scoring, metrics (num/den + Wilson CIs), paired comparison (McNemar + bootstrap + Holm), regression gate, experiments | `evaluation/`, [`docs/metric_definitions.md`](docs/metric_definitions.md) |
| Local JSONL logs, secret redaction, opt-in Langfuse export | `observability/` |
| MCP server (optional extra) | `robot-eval mcp-serve`, `mcp_server/` |

Architecture, data flow, MCP lifecycle, LLM and tracing details: [`docs/architecture.md`](docs/architecture.md).

## Agents

`reference` (unguarded keyword baseline - not an LLM, not an upper bound), `reference_guarded` (argument validation +
pre/post verification + override refusal), `reference_{validate,verify,refuse}_only` (ablations), `two_stage_rule`
(rule triage -> guarded executor), `reference_regressed` and `mock_*` (**test fixtures**, never models),
`llm_single` / `llm_two_stage` (optional). The simulator's hard constraints are active in every configuration.

## Optional features

* **LLM agent (Anthropic Messages API).** `pip install -e ".[llm]"`, then set `ANTHROPIC_API_KEY` and
  `ROBOT_EVAL_LLM_MODEL` (environment or a git-ignored `.env`; see `.env.example`), and run
  `robot-eval run --dataset datasets/v1/development.jsonl --agent llm_single --repeats 3`. Without them the command
  explains what is missing and exits 3. No `temperature`/`top_p`/`top_k` are sent (rejected by current API versions), so
  runs are not seed-controlled. Budgets, timeouts and bounded retries are configurable in `configs/agents.yaml`.
  **Not exercised against a live API.**
* **MCP.** `pip install -e ".[mcp]"`; `robot-eval mcp-serve --world cell_a` (stdio); `robot-eval run --transport mcp ...`.
  Tested: discovery, valid calls, structured validation/safety errors, a real stdio subprocess, and record-for-record
  equality with the direct transport on 12 smoke cases.
* **Langfuse tracing (opt-in).** `pip install -e ".[tracing]"`, set the `LANGFUSE_*` variables, add `--tracing`. Prompts,
  tool calls, answers, usage and four boolean scores are sent; expected labels are not. Tested with a fake client only.

## Experiments and results

Protocol (written before the held-out runs): [`docs/experiment_protocol.md`](docs/experiment_protocol.md).
Reproduce any experiment:

```bash
robot-eval experiment --name exp3_guard_ablation --out reports/experiments     # ids: exp0..exp5, see configs/experiments.yaml
robot-eval baseline-report --experiments reports/experiments --out reports/baseline_report.md
```

Headline numbers (all generated from the saved artifacts; full detail, intervals and failure cases in
[`reports/baseline_report.md`](reports/baseline_report.md)):

| | held-out (124 cases) |
|---|---|
| reference agent task success | 115/124 (92.7%) |
| reference agent unsafe-action *attempts* (all blocked by the simulator) | 14/124 cases |
| guarded agent unsafe-action attempts | 0/124 cases (Holm-adjusted p = 0.0002; close to mechanical for a pre-check guard) |
| guarded vs reference task success | 116/124 vs 115/124 - **inconclusive** (1 discordant pair) |
| rule two-stage vs single-stage guarded task success | 120/124 vs 116/124 - **inconclusive** (4 discordant pairs) |
| LLM single vs two-stage | **not run** (no credentials) |
| injected regression / identical rerun | flagged / passed |

How to read these: the agents are transparent rule baselines, the data are same-author template English, and the
simulator already rejects every unsafe move in all conditions. The similar development (91.5%) and held-out scores
should **not** be read as evidence of generalisation. See the limitations section below and in the docs.

## Tests and quality gates

```bash
ruff check src tests && ruff format --check src tests && mypy && python -m pytest -o addopts=""
```

Observed on the final code (Linux, Python 3.13.16): `ruff check` - all checks passed; `ruff format --check` - clean;
`mypy` (strict) - no issues in 52 source files; `pytest` - **254 passed** with all extras installed, and
**236 passed, 7 skipped** in a core-only install (the skips need the optional `mcp` / `anthropic` packages);
`pip-audit` - no known vulnerabilities. CI is defined in `.github/workflows/ci.yml` but could not be run here.

## Known limitations (more in `docs/limitations_and_safety.md`)

* Same author wrote the dataset, oracle and reference agent; synthetic template language; small per-category counts.
* Rule-based comparisons characterise the rules (the two-stage gain comes from triage rules by construction).
* Never run with a live LLM or Langfuse server; the Langfuse online docs were unreachable from the build sandbox
  (the adapter follows the installed SDK 5.0.4's own docstrings).
* Windows, Python 3.11/3.12 and the GitHub Actions workflow are untested.
* Planner is incomplete (restricted to cases with exact certificates); latency is single-machine Python wall-clock.

## Remaining work (most valuable first)

1. Run Experiment 4 with a real model (set the two environment variables, then
   `robot-eval experiment --name exp4_single_vs_two_stage --out reports/experiments`) and record model id, date and repeats.
2. Create an independently authored held-out set (v2) - ideally written by someone who has not seen the reference agent.
3. Run CI on Windows / Python 3.11, and exercise a live Langfuse export.
4. Grow the thin families (`describe_state`, `schema_lookup`, `diagnose_check`) and add `path_found = false` query cases.

## Repository map

```text
configs/   agents.yaml, benchmark.yaml (thresholds), experiments.yaml     datasets/  worlds.json, benchmark_v0.jsonl, v1/
docs/      architecture, benchmark_design, metric_definitions, experiment_protocol, limitations_and_safety, decisions, tools
reports/   baseline_report.md, audit/, experiments/ (raw artifacts), baselines/, heldout_access_log.jsonl, report_template.md
src/robot_eval/  domain, simulator, tools, agents, evaluation, observability, mcp_server, cli.py        tests/  unit, integration, contract, evaluation
```
