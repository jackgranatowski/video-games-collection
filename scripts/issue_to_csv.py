#!/usr/bin/env python3
"""Przeklada zgloszenie z formularza Issue na zmiane w data/games.csv.

Uruchamiane przez .github/workflows/issue-to-collection.yml. Tresc zgloszenia
przychodzi w zmiennej srodowiskowej ISSUE_BODY (nigdy przez argumenty powloki -
to tresc pisana przez uzytkownika).

Uruchomienie:
    ISSUE_BODY="..." python3 scripts/issue_to_csv.py add
    ISSUE_BODY="..." python3 scripts/issue_to_csv.py update
"""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.csv"
SUMMARY = ROOT / "issue-result.md"

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

# Poczatek etykiety z formularza -> kolumna w CSV. Porownanie po malych literach,
# wiec obie wersje formularza ("Status" i "Nowy status") trafiaja w to samo.
LABEL_TO_FIELD = [
    ("tytuł", "title"),
    ("rok premiery", "year"),
    ("nowy status", "status"),
    ("status", "status"),
    ("platformy", "platforms"),
    ("mam?", "owned"),
    ("priorytet", "priority"),
    ("vr", "vr"),
    ("ocena", "rating"),
    ("rok ukończenia", "finished_year"),
    ("hype", "hype"),
    ("recenzja", "review"),
    ("dodane na blogu?", "blog"),
    ("tagi", "tags"),
    ("notatki", "notes"),
]

EMPTY_MARKERS = {
    "_no response_",
    "_brak odpowiedzi_",
    "-",
    "",
    # Pierwsza pozycja list wyboru - GitHub nie pozwala na pusta opcje.
    "bez zmian",
    "nie ustawiam",
}

# Tylko te pola pochodza z list wyboru i maja postac "kod — opis".
# Reszta to wolny tekst, w ktorym myslnik jest zwyklym znakiem.
DROPDOWN_FIELDS = {"status", "owned", "priority", "vr", "review", "blog"}


def parse_issue(body: str) -> dict[str, str]:
    """Rozbija tresc zgloszenia na pary pole -> wartosc."""
    fields: dict[str, str] = {}
    blocks = re.split(r"^###\s+", body.replace("\r\n", "\n"), flags=re.MULTILINE)

    for block in blocks[1:]:
        head, _, rest = block.partition("\n")
        label = head.strip().lower()
        value = rest.strip()

        if value.lower() in EMPTY_MARKERS:
            continue

        for prefix, field in LABEL_TO_FIELD:
            if label.startswith(prefix):
                if field in DROPDOWN_FIELDS:
                    # Listy wyboru wracaja jako "backlog — do ogrania".
                    value = re.split(r"\s+[—–-]\s+", value)[0].strip()
                # CSV to jedna linia na gre - wieloliniowe notatki sklejamy.
                fields[field] = re.sub(r"\s+", " ", value).strip()
                break

    return fields


def read_games() -> list[dict[str, str]]:
    with GAMES.open(encoding="utf-8", newline="") as handle:
        return [
            {key: (value or "") for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def write_games(rows: list[dict[str, str]]) -> None:
    rows.sort(key=lambda row: (row["title"].lower(), row["year"]))
    with GAMES.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def finish(ok: bool, message: str) -> int:
    SUMMARY.write_text(message + "\n", encoding="utf-8")
    print(message)
    return 0 if ok else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in {"add", "update"}:
        sys.exit("Uzycie: issue_to_csv.py add|update")

    body = os.environ.get("ISSUE_BODY", "")
    if not body.strip():
        return finish(False, "❌ Puste zgłoszenie — nie ma czego przetworzyć.")

    fields = parse_issue(body)
    title = fields.get("title", "").strip()
    if not title:
        return finish(False, "❌ Brak tytułu — nie wiem, której gry dotyczy zgłoszenie.")

    rows = read_games()
    existing = [row for row in rows if row["title"].lower() == title.lower()]

    if mode == "add":
        row = {column: "" for column in COLUMNS}
        row.update({key: value for key, value in fields.items() if key in COLUMNS})
        row["title"] = title
        rows.append(row)
        write_games(rows)

        note = ""
        if existing:
            note = (
                f"\n\n⚠️ W kolekcji był już wpis o tym tytule "
                f"({len(existing)}). Jeśli to pomyłka, usuń zbędny wiersz."
            )
        details = ", ".join(
            f"{key}={value}" for key, value in row.items() if value and key != "title"
        )
        return finish(True, f"✅ Dodano **{title}**\n\n`{details or 'bez dodatkowych pól'}`{note}")

    if not existing:
        return finish(
            False,
            f"❌ Nie znalazłem gry **{title}** w kolekcji. "
            "Sprawdź pisownię albo użyj formularza „Dodaj grę”.",
        )
    if len(existing) > 1:
        return finish(
            False,
            f"❌ Tytuł **{title}** występuje {len(existing)} razy — "
            "nie wiem, który wiersz zmienić. Popraw go ręcznie w `data/games.csv`.",
        )

    row = existing[0]
    changes = []
    for key, value in fields.items():
        if key == "title" or key not in COLUMNS:
            continue
        if row[key] != value:
            changes.append(f"{key}: `{row[key] or '—'}` → `{value}`")
            row[key] = value

    if not changes:
        return finish(True, f"ℹ️ **{title}** — nic się nie zmieniło.")

    write_games(rows)
    return finish(True, f"✅ Zaktualizowano **{title}**\n\n" + "\n".join(f"- {c}" for c in changes))


if __name__ == "__main__":
    raise SystemExit(main())
