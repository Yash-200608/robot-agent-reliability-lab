from __future__ import annotations

from pathlib import Path

from robot_eval.tools.docgen import render

ROOT = Path(__file__).resolve().parents[2]


def test_tools_doc_is_current() -> None:
    committed = (ROOT / "docs" / "tools.md").read_text(encoding="utf-8")
    assert committed == render(ROOT / "datasets"), (
        "regenerate with: python -m robot_eval.tools.docgen"
    )


def test_required_docs_exist() -> None:
    for name in (
        "architecture",
        "benchmark_design",
        "metric_definitions",
        "experiment_protocol",
        "limitations_and_safety",
        "decisions",
        "tools",
        "gate0_audit",
    ):
        assert (ROOT / "docs" / f"{name}.md").is_file(), name
    assert (ROOT / ".env.example").is_file() and (ROOT / "reports" / "report_template.md").is_file()
