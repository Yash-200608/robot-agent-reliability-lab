# Running this project on your own computer

The project was built in a cloud sandbox and is delivered as `robot-agent-reliability-lab.zip` (SHA-256 in
`robot-agent-reliability-lab.zip.sha256`). Nothing in it needs the cloud: it is pure Python, CPU-only, and needs no
account, API key or network access for the core benchmark.

## 1. Prerequisites
* Python 3.11 or newer (tested only on 3.13.16, Linux). Check with `python --version` (on Windows also try `py -3 --version`).
* Optional: Git. Nothing else.

## 2. Unpack and install

Windows PowerShell:

```powershell
Expand-Archive robot-agent-reliability-lab.zip -DestinationPath .
cd robot-agent-reliability-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
pip install -e ".[dev]"
```

macOS / Linux:

```bash
unzip robot-agent-reliability-lab.zip && cd robot-agent-reliability-lab
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 3. Check that it works on your machine

```bash
python -m pytest -o addopts=""                       # core install: expect "236 passed, 7 skipped" (optional extras absent)
robot-eval validate-dataset --dataset datasets/benchmark_v0.jsonl datasets/v1/development.jsonl datasets/v1/heldout_test.jsonl
robot-eval run --dataset datasets/benchmark_v0.jsonl --agent reference
```

Windows has **not** been tested by the author. If a test fails only on your machine, please keep the output - that is
exactly the information the project still lacks. If `robot-eval` is not found, use `python -m robot_eval ...`.

## 4. Optional extras
`pip install -e ".[mcp]"` (MCP server), `".[llm]"` (Anthropic agent; set `ANTHROPIC_API_KEY` and
`ROBOT_EVAL_LLM_MODEL` in your environment or a local `.env`, never in the repository), `".[tracing]"` (Langfuse), `".[all]"`.
With all extras the suite should report 254 passed.

## 5. If you put it under Git
Dataset hashes are computed over raw bytes, so line endings must stay LF. The included `.gitattributes` enforces that;
additionally run `git config core.autocrlf false` in the repository *before* the first `git add`. If you ever see
"dataset hashes differ" or `test_generator_is_reproducible` failing only on Windows, line endings are the first suspect.

## 6. Starting from scratch locally (regenerate everything)

```bash
robot-eval generate-dataset                                   # byte-identical to the shipped datasets (seeded)
robot-eval experiment --name exp2_reference_baseline --out reports/experiments
robot-eval baseline-report --experiments reports/experiments --out reports/baseline_report.md
```
Re-running experiments appends to `reports/heldout_access_log.jsonl` (by design) and writes new timestamped directories.
Wall-clock latencies will differ on your machine; every other number should reproduce exactly.

## 7. Continuing development with Claude on your computer
This cloud session cannot attach to your machine. To keep working with Claude locally, open the unpacked folder in
Claude Code on your computer (desktop app or CLI) and start a new session there; the repository documents itself
(`README.md`, `docs/`), and `docs/experiment_protocol.md` section 11 records the held-out discipline to preserve.
