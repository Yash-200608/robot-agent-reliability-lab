"""Allows ``python -m robot_eval ...`` (useful on Windows where console scripts may not be on PATH)."""

from robot_eval.cli import main

raise SystemExit(main())
