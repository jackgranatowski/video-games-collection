#!/usr/bin/env python3
"""Sprawdza poprawnosc data/games.csv.

Bledy (exit 1) to rzeczy, ktore rozwalilyby strone albo oznaczaja pomylke przy
edycji. Ostrzezenia (exit 0) to rzeczy do przejrzenia na spokojnie - literowki
w platformach, duplikaty tytulow, brakujace lata.

Uruchomienie:
    python3 scripts/validate.py           # sprawdz
    python3 scripts/validate.py --fix     # posortuj i przepisz plik
"""

from __future__ import annotations

import collections
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.csv"

COLUMNS = [
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

STATUSES = {
    "playing",
    "want_to_try",
    "limbo",
    "backlog",
    "upcoming",
    "completed",
    "played",
    "not_interested",
}
PRIORITIES = {"high", "normal", "someday", "skip", ""}
YES_NO = {"yes", "no", ""}
VR_VALUES = {"no", "yes", "optional", "required", ""}
REVIEWS = {"todo", "done", "not_needed", ""}

# Ponizej tylu wystapien platforma wyglada na literowke i trafia do ostrzezen.
RARE_PLATFORM_THRESHOLD = 2


def sort_key(row: dict[str, str]) -> tuple[str, str]:
    return (row["title"].lower(), row["year"])


def check(rows: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    def in_set(row_no, field, allowed, label):
        value = rows[row_no - 2][field]
        if value not in allowed:
            errors.append(
                f"wiersz {row_no}: {field}='{value}' - dozwolone: {label}"
            )

    def numeric(row_no, field, low, high):
        value = rows[row_no - 2][field]
        if value == "":
            return
        if not value.isdigit() or not low <= int(value) <= high:
            errors.append(
                f"wiersz {row_no}: {field}='{value}' - oczekiwana liczba {low}-{high}"
            )

    titles: dict[str, list[int]] = collections.defaultdict(list)
    platforms: collections.Counter = collections.Counter()

    for index, row in enumerate(rows):
        row_no = index + 2  # +1 naglowek, +1 numeracja od jedynki

        title = row["title"]
        if not title.strip():
            errors.append(f"wiersz {row_no}: pusty tytul")
        elif title != title.strip():
            errors.append(f"wiersz {row_no}: tytul ze spacja na brzegu: '{title}'")
        else:
            titles[title.lower()].append(row_no)

        in_set(row_no, "status", STATUSES, ", ".join(sorted(STATUSES)))
        in_set(row_no, "priority", PRIORITIES, "high, normal, someday, skip lub puste")
        in_set(row_no, "owned", YES_NO, "yes, no lub puste")
        in_set(row_no, "vr", VR_VALUES, "no, yes, optional, required lub puste")
        in_set(row_no, "review", REVIEWS, "todo, done, not_needed lub puste")
        in_set(row_no, "blog", YES_NO, "yes, no lub puste")

        numeric(row_no, "year", 1950, 2040)
        numeric(row_no, "finished_year", 1950, 2040)
        numeric(row_no, "rating", 1, 5)
        numeric(row_no, "hype", 1, 10)

        if row["status"] == "completed" and row["priority"] in {"high", "normal"}:
            warnings.append(
                f"wiersz {row_no} ({title}): ukonczona, a priorytet '{row['priority']}'"
            )

        for platform in row["platforms"].split(";"):
            if platform:
                platforms[platform] += 1

    for title, numbers in titles.items():
        if len(numbers) > 1:
            warnings.append(
                f"tytul '{title}' wystepuje {len(numbers)}x - wiersze {numbers}"
            )

    for platform, count in platforms.items():
        if count <= RARE_PLATFORM_THRESHOLD:
            warnings.append(
                f"platforma '{platform}' uzyta {count}x - literowka? "
                "(jesli poprawna, zignoruj)"
            )

    if rows != sorted(rows, key=sort_key):
        errors.append(
            "plik nie jest posortowany alfabetycznie - uruchom: "
            "python3 scripts/validate.py --fix"
        )

    return errors, warnings


def main() -> int:
    if not GAMES.exists():
        sys.exit(f"Brak pliku: {GAMES}")

    with GAMES.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            sys.exit(
                f"Zle naglowki.\n  oczekiwane: {COLUMNS}\n  znalezione: {reader.fieldnames}"
            )
        rows = [{key: (value or "") for key, value in row.items()} for row in reader]

    if "--fix" in sys.argv:
        rows.sort(key=sort_key)
        with GAMES.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Posortowano i zapisano {len(rows)} wierszy.")

    errors, warnings = check(rows)

    print(f"Sprawdzono {len(rows)} gier.")
    if warnings:
        print(f"\nOstrzezenia ({len(warnings)}):")
        for warning in warnings:
            print(f"  ! {warning}")
    if errors:
        print(f"\nBledy ({len(errors)}):")
        for error in errors:
            print(f"  X {error}")
        return 1

    print("\nOK - brak bledow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
