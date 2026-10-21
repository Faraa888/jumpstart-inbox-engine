#!/usr/bin/env python3
"""Build out/console.html: one self-contained file, no network, works offline.

    python3 build_console.py     (run run.py, eval/score.py and eval/scale_test.py first)

serve.py uses build_html(live_mode=True) to serve the same console live at http://localhost:8080/console.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))


def console_data():
    data = json.load(open(os.path.join(ROOT, "out", "console_data.json")))
    ev = json.load(open(os.path.join(ROOT, "eval", "report.json")))
    first = open(os.path.join(ROOT, "eval", "first_run_before_fixes.txt")).read()
    m = re.search(r"ADVERSARIAL SET \(n=(\d+)\): (\d+)/", first)
    data["eval"] = {"gold": ev["gold"], "adversarial": ev["adversarial"]}
    data["first_run"] = {"n": int(m.group(1)), "pass": int(m.group(2))}
    data["scale"] = json.load(open(os.path.join(ROOT, "eval", "scale_report.json")))
    for k in ("week1", "week2"):
        data["scale"][k] = {x: data["scale"][k][x] for x in
                            ("auto_replies", "silent", "person", "partner", "person_hours", "ops_person_emails")}
    return data


def build_html(live_mode=False, live_emails=None, data=None):
    data = dict(data or console_data())
    data["live_mode"] = live_mode
    data["live_emails"] = live_emails or []
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return open(os.path.join(ROOT, "ui", "console_template.html"), encoding="utf-8").read().replace("__DATA__", payload)


if __name__ == "__main__":
    html = build_html()
    out = os.path.join(ROOT, "out", "console.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")
