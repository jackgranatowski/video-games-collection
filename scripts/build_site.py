#!/usr/bin/env python3
"""Buduje statyczna strone do _site/ na podstawie data/games.csv.

Strona jest w calosci statyczna - dane laduja w games.json, reszta to trzy pliki
z katalogu site/. Zadnego backendu, zadnej bazy.

Uruchomienie:
    python3 scripts/build_site.py
    python3 -m http.server -d _site 8000     # podglad lokalny
"""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.csv"
SITE = ROOT / "site"
OUT = ROOT / "_site"

# Kolejnosc pol w tablicach games.json - musi zgadzac sie z FIELDS w app.js.
FIELDS = [
    "title",
    "year",
    "status",
    "priority",
    "owned",
    "platforms",
    "vr",
    "rating",
    "finished_year",
    "hype",
    "review",
    "blog",
    "tags",
    "notes",
]

LIST_FIELDS = {"platforms", "tags"}
NUMERIC_FIELDS = {"year", "rating", "finished_year", "hype"}


def main() -> int:
    with GAMES.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    games = []
    for row in rows:
        record = []
        for field in FIELDS:
            value = (row.get(field) or "").strip()
            if field in LIST_FIELDS:
                record.append([part for part in value.split(";") if part])
            elif field in NUMERIC_FIELDS:
                record.append(int(value) if value.isdigit() else None)
            else:
                record.append(value)
        games.append(record)

    payload = {
        "generated": date.today().isoformat(),
        "fields": FIELDS,
        "games": games,
        "facets": {
            "platforms": sorted(
                Counter(p for g in games for p in g[FIELDS.index("platforms")]),
                key=lambda name: name.lower(),
            ),
            "tags": sorted(
                Counter(t for g in games for t in g[FIELDS.index("tags")]),
                key=lambda name: name.lower(),
            ),
        },
    }

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SITE, OUT)
    (OUT / "games.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    size = (OUT / "games.json").stat().st_size
    print(f"Zbudowano {OUT.relative_to(ROOT)}: {len(games)} gier, games.json {size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
