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
METADATA = ROOT / "data" / "metadata.csv"
SITE = ROOT / "site"
OUT = ROOT / "_site"

# Kolejnosc pol w tablicach games.json - musi zgadzac sie z FIELDS w app.js.
# Ostatnie cztery pochodza z RAWG (data/metadata.csv), reszta z games.csv.
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
    "genres",
    "cover",
    "metacritic",
    "playtime",
    "source",
    "source_slug",
]

LIST_FIELDS = {"platforms", "tags", "genres"}
NUMERIC_FIELDS = {"year", "rating", "finished_year", "hype", "metacritic", "playtime"}

# Pola dokladane z metadata.csv - games.csv nie ma na nie wplywu i odwrotnie.
META_FIELDS = ["genres", "cover", "metacritic", "playtime", "source", "source_slug"]


def read_metadata() -> dict[str, dict[str, str]]:
    """Metadane z RAWG/IGDB, po tytule. Brak pliku = strona bez okladek."""
    if not METADATA.exists():
        return {}
    with METADATA.open(encoding="utf-8", newline="") as handle:
        return {
            row["title"]: row
            for row in csv.DictReader(handle)
            if row.get("source_id")  # niepewne trafienia pomijamy
        }


def main() -> int:
    with GAMES.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    metadata = read_metadata()

    games = []
    for row in rows:
        meta = metadata.get(row["title"], {})
        record = []
        for field in FIELDS:
            source = meta if field in META_FIELDS else row
            value = (source.get(field) or "").strip()
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
            "genres": sorted(
                Counter(g2 for g in games for g2 in g[FIELDS.index("genres")]),
                key=lambda name: name.lower(),
            ),
        },
        "enriched": sum(1 for g in games if g[FIELDS.index("source")]),
    }

    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SITE, OUT)
    (OUT / "games.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    size = (OUT / "games.json").stat().st_size
    print(
        f"Zbudowano {OUT.relative_to(ROOT)}: {len(games)} gier "
        f"({payload['enriched']} z metadanymi), games.json {size // 1024} KB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
