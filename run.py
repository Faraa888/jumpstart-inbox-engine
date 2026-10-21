#!/usr/bin/env python3
"""Run the whole pipeline over data/inbox.csv in dry-run mode. No API keys needed.

    python3 run.py

Writes to out/: inbox_triaged.csv (your sheet plus decisions), console_data.json,
metrics.json and inbox.db (SQLite: emails, classifications, decisions, action log).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.pipeline import run  # noqa: E402

if __name__ == "__main__":
    run(os.path.dirname(os.path.abspath(__file__)))
