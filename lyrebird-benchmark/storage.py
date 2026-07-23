"""Persists every benchmark run to results/ on disk.

The Streamlit UI reruns the whole script on every interaction and resets
session_state on a browser refresh, so anything kept only in memory is lost
the moment the page reloads. Writing each run to disk here is what makes
results survive a refresh — the CLI (app.py) already did this; the UI now
goes through the same helper so nothing is duplicated or gets out of sync.
"""

import csv
import json
import os
import time

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def save_results(rows, tag):
    """Write one run's rows to results/<timestamp>-<tag>.{json,csv}."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = os.path.join(RESULTS_DIR, f"{stamp}-{tag}.json")
    csv_path = os.path.join(RESULTS_DIR, f"{stamp}-{tag}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
            writer.writeheader()
            writer.writerows(rows)

    return json_path, csv_path


def load_all_results():
    """Every row from every saved run on disk, newest run first."""
    if not os.path.isdir(RESULTS_DIR):
        return []
    all_rows = []
    for fname in sorted(os.listdir(RESULTS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(RESULTS_DIR, fname), encoding="utf-8") as f:
                rows = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for row in rows:
            row["_run"] = fname
        all_rows.extend(rows)
    return all_rows
