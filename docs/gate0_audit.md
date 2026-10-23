# Gate 0 — Repository audit and plan alignment

## What was found

The implementation plan assumes an existing `robot_eval` package (24-case `benchmark_v0.jsonl`,
keyword reference agent, simulator functions, CLI, tests, sample outputs).

**That repository was not available in the session that produced this code.** The working directory
was empty and not a git repository, no repositories were attached to the session, the GitHub token
in the environment was invalid, and a filesystem-wide search found no `robot_eval` package and no
`benchmark_v0.jsonl`. After being told this, the user instructed: *"Start from scratch."*

Consequences, stated plainly:

* There was nothing to run for the "existing tests" step. **No existing test result exists** and
  none is claimed.
* Nothing from the original repository was reused or preserved. The package name (`robot_eval`),
  CLI name (`robot-eval`), dataset file name (`datasets/benchmark_v0.jsonl`) and the 24-case size
  follow the plan, but **the contents of this repository's v0 suite are newly authored** here and are
  *not* the user's original 24 cases. If the original repository is later merged with this one,
  expect to reconcile the v0 files, CLI and tests by hand.
* Because there is no prior behaviour to stay compatible with, there are no breaking changes to
  record in migration notes.

## Environment used (tested combination)

| Item | Version |
|---|---|
| Python | 3.13.16 (Linux). The package declares `>=3.11`; only 3.13 was exercised. |
| pydantic | 2.14.1 |
| PyYAML | 6.0.3 |
| numpy | 2.5.4 |
| mcp (optional extra) | 2.3.0 |
| anthropic (optional extra) | 2.1.0 |
| langfuse (optional extra) | 5.0.4 |
| pytest / ruff / mypy | 9.1.1 / 0.17.1 / 2.4.0 (pytest 8.4.2 was used until `pip-audit` flagged PYSEC-2026-1845; upgraded to the fixed 9.x) |

The Windows/i5 requirement could not be exercised (the session runs Linux). The code uses only
`pathlib`, UTF-8 file I/O and no platform-specific calls, and README commands are given for both
PowerShell and POSIX shells, but **Windows execution is untested**.

## Gap report (plan vs. starting point)

Everything in the plan was a gap. The implementation order followed Gates 1–8 of the plan; the
state of each gate is recorded in the final report and in `README.md`.
