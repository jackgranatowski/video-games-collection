#!/usr/bin/env python3
"""Jednorazowa migracja: data/archive/Kolekcja_gier.xlsx -> data/games.csv.

Skrypt jest zachowany w repo, zeby migracje dalo sie odtworzyc i sprawdzic,
co dokladnie stalo sie z ktorym polem. Do codziennej pracy nie jest potrzebny.

Uruchomienie:
    python3 scripts/migrate_xlsx.py
"""

from __future__ import annotations

import collections
import csv
import re
import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    sys.exit("Brak openpyxl. Zainstaluj: pip install openpyxl")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "archive" / "Kolekcja_gier.xlsx"
TARGET = ROOT / "data" / "games.csv"
SHEET = "Moja kolekcja gier"

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

# Naglowki sekcji w arkuszu -> (status, dodatkowe tagi, domyslny priorytet).
# Klucz porownywany po normalizacji bialych znakow.
SECTIONS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "OGRYWAM OBECNIE": ("playing", (), ""),
    "Chcę tylko spróbować / sprawdzić": ("want_to_try", (), ""),
    "GAME LIMBO - JESTEM ZAINTERESOWANY, ALE NIE PALI SIĘ": ("limbo", (), ""),
    "Gry multiplayer / MMO / sportowe / endless / mobilne w które regularnie "
    "(lub od czasu do czasu) gram": ("playing", ("regularne", "multiplayer"), ""),
    "Gry do przejścia z Madzią": ("backlog", ("razem",), ""),
    "GRY PSVR do ogrania priorytetowo": ("backlog", ("vr",), "high"),
    "Gry PSVR które można ograć też na psvr2": ("backlog", ("vr", "psvr2"), ""),
    "Gry PSVR z fabułą do przejścia": ("backlog", ("vr", "fabuła"), ""),
    "Gry ukończone z dodatkami fabularnymi do przejścia": (
        "completed",
        ("dodatki-do-ogrania",),
        "",
    ),
    "Gry ukończone, w które chcę jeszcze zagrać / trofea do powbijania / "
    "Remake lub remaster do przejścia": ("completed", ("wrócić",), ""),
    "Nowości przed premierą do sprawdzenia": ("upcoming", (), ""),
    "GRY DO PRZEJŚCIA NA EMERYTURZE - JESTEM ZAINTERESOWANY, ALE EWENTUALNIE "
    "MOGĘ OLAĆ": ("backlog", ("emerytura",), "someday"),
    "GAME LIMBO [VR] - Chciałbym zagrać i przejść, ale nie mam konsoli lub "
    "sprzętu, albo chciałbym przejść na PSVR2": ("limbo", ("vr", "brak-sprzętu"), ""),
    "Gry ukończone/wyczerpane": ("completed", (), ""),
    "Gry multiplayer/endless i inne, których nie ukończyłem/wyczerpałem, ale "
    "chociaż trochę ograłem": ("played", (), ""),
    "Gry PSVR, które mnie nie interesują": ("not_interested", ("vr",), "skip"),
    "Nie interesują mnie / nie mam czasu / grałem, ale nie mam zamiaru kończyć": (
        "not_interested",
        (),
        "skip",
    ),
}

PRIORITY_MAP = {
    "Z miłą chęcią, priorytetowo": "high",
    "Musze ograć, żeby mieć spokój": "high",
    "Do ogrania na pewno, ale się nie pali": "normal",
    "Kiedyś, może na emeryturze?": "someday",
    "Olewam, nie interesuje mnie": "skip",
}

VR_MAP = {
    "Nie": "no",
    "Tak": "yes",
    "Tak, wymagane": "required",
    "Opcjonalnie": "optional",
}

REVIEW_MAP = {
    "Nie trzeba": "not_needed",
    "Jest": "done",
    "Do napisania": "todo",
}

# Warianty tej samej platformy, ktore w arkuszu roznily sie zapisem.
# Uwaga: '+' nigdy nie jest separatorem - to czesc nazwy (PS+, PS+ Premium).
PLATFORM_ALIASES = {
    "xgp": "Xbox Game Pass",
    "game pass": "Xbox Game Pass",
    "ps vita": "PSV",
    "ps1": "PSX",
    "psp go": "PSP",
    "ps+premium": "PS+ Premium",
    "psn +": "PS+",
    "psn+": "PS+",
    # Jednoznaczne literowki i skroty z arkusza.
    "eoic": "Epic",
    "prima gaming": "Prime Gaming",
    "wiiu": "Wii U",
    "switch": "Nintendo Switch",
    "x360": "Xbox 360",
    "tylko ps4": "PS4",
}

PLATFORM_SPLIT = re.compile(r"[/,()]")

stats: collections.Counter = collections.Counter()
warnings: list[str] = []


def norm_ws(value: str) -> str:
    """Skleja wieloliniowe i podwojnie spacjowane napisy w jedna linie."""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_title(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return norm_ws(value)


def as_year(value) -> str:
    if value in (None, "", "ND"):
        return ""
    try:
        year = int(float(value))
    except (TypeError, ValueError):
        warnings.append(f"rok nie do odczytania: {value!r}")
        return ""
    if not 1950 <= year <= 2040:
        warnings.append(f"rok poza zakresem: {year}")
        return ""
    return str(year)


def as_number(value, low: int, high: int, field: str) -> tuple[str, str]:
    """Zwraca (liczba, odrzucona_wartosc). 'Nie' i puste traktujemy jako brak."""
    if value in (None, "", "Nie", "ND"):
        return "", ""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return "", norm_ws(value)
    if not low <= number <= high:
        warnings.append(f"{field} poza zakresem {low}-{high}: {number}")
        return "", ""
    return str(number), ""


def collect_platform_casing(rows) -> dict[str, str]:
    """Dla kazdej platformy wybiera najczestszy wariant zapisu z arkusza."""
    seen: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for row in rows:
        raw = row[9]
        if raw in (None, ""):
            continue
        for token in PLATFORM_SPLIT.split(str(raw)):
            token = norm_ws(token)
            if token:
                seen[token.lower()][token] += 1
    return {key: counter.most_common(1)[0][0] for key, counter in seen.items()}


def parse_platforms(raw, casing: dict[str, str]) -> str:
    if raw in (None, ""):
        return ""
    out: list[str] = []
    for token in PLATFORM_SPLIT.split(str(raw)):
        # '?' oznaczalo niepewnosc co do posiadania, nie inna platforme.
        token = norm_ws(token).rstrip("?")
        if not token:
            continue
        key = token.lower()
        name = PLATFORM_ALIASES.get(key) or casing.get(key, token)
        if name not in out:
            out.append(name)
    return ";".join(out)


def main() -> int:
    if not SOURCE.exists():
        sys.exit(f"Brak pliku zrodlowego: {SOURCE}")

    workbook = openpyxl.load_workbook(SOURCE, data_only=True)
    sheet = workbook[SHEET]
    rows = list(sheet.iter_rows(min_row=2, values_only=True))

    section_keys = {norm_ws(key): value for key, value in SECTIONS.items()}
    casing = collect_platform_casing(rows)

    current: tuple[str, tuple[str, ...], str] | None = None
    games: list[dict[str, str]] = []

    for number, row in enumerate(rows, start=2):
        raw_title = row[0]
        if raw_title in (None, ""):
            continue

        rest_filled = any(cell not in (None, "") for cell in row[1:])
        title = clean_title(raw_title)

        # Wiersz z sama nazwa w kolumnie A moze byc naglowkiem sekcji albo gra
        # bez zadnych danych - rozstrzyga lista znanych naglowkow.
        if not rest_filled and norm_ws(title) in section_keys:
            current = section_keys[norm_ws(title)]
            stats["sekcje"] += 1
            continue

        if current is None:
            warnings.append(f"wiersz {number}: '{title}' przed pierwsza sekcja - pominiety")
            stats["pominiete"] += 1
            continue

        status, section_tags, section_priority = current
        tags = list(section_tags)
        notes: list[str] = []

        priority = PRIORITY_MAP.get(row[4]) if row[4] not in (None, "") else None
        if priority is None:
            priority = section_priority
        # Trzy kolumny "Tak/Nie" niosly sygnal tylko przy "Tak" - reszta to
        # artefakt przeciagania formuly w dol. Zachowujemy je jako tagi, zeby
        # nic nie zginelo, ale priorytet liczymy wedlug kolejnosci waznosci.
        if row[1] == "Tak":
            tags.append("chcę-zagrać")
            priority = priority or "high"
        if row[3] == "Tak":
            tags.append("nie-pali-się")
            priority = priority or "someday"
        if row[2] == "Tak":
            tags.append("można-olać")
            priority = priority or "skip"

        rating, rating_reject = as_number(row[12], 1, 5, "ocena")
        platforms_raw = row[9]
        if rating_reject:
            # W kilku wierszach ocena i platforma sie rozjechaly.
            platforms_raw = f"{platforms_raw}/{rating_reject}" if platforms_raw else rating_reject
            warnings.append(
                f"wiersz {number} ({title}): '{rating_reject}' w kolumnie oceny "
                "-> przeniesione do platform"
            )
            stats["ocena_naprawiona"] += 1

        hype, _ = as_number(row[10], 1, 10, "hype")

        if row[15] not in (None, ""):
            notes.append(norm_ws(row[15]))

        games.append(
            {
                "title": title,
                "year": as_year(row[5]),
                "status": status,
                "priority": priority or "",
                "owned": {"Tak": "yes", "Nie": "no"}.get(row[8], ""),
                "platforms": parse_platforms(platforms_raw, casing),
                "vr": VR_MAP.get(row[11], ""),
                "rating": rating,
                "finished_year": as_year(row[7]),
                "hype": hype,
                "review": REVIEW_MAP.get(row[14], ""),
                "blog": "yes" if row[13] == "Tak" else "",
                "tags": ";".join(dict.fromkeys(tags)),
                "notes": " | ".join(notes),
            }
        )
        stats[f"status:{status}"] += 1

    # Wiersze identyczne w kazdym polu to duplikaty z kopiowania - zostaje jeden.
    unique: dict[tuple, dict[str, str]] = {}
    for game in games:
        key = tuple(game[column] for column in COLUMNS)
        if key in unique:
            stats["duplikaty_identyczne"] += 1
            continue
        unique[key] = game
    games = list(unique.values())

    games.sort(key=lambda game: (game["title"].lower(), game["year"]))

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(games)

    print(f"Zapisano {len(games)} gier -> {TARGET.relative_to(ROOT)}")
    for key, value in sorted(stats.items()):
        print(f"  {key}: {value}")
    if warnings:
        print(f"\nUwagi ({len(warnings)}):")
        for warning in warnings[:20]:
            print(f"  - {warning}")
        if len(warnings) > 20:
            print(f"  ... i {len(warnings) - 20} wiecej")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
