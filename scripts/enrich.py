#!/usr/bin/env python3
"""Dociaga metadane gier z RAWG do data/metadata.csv.

Zasada: ten skrypt NIGDY nie pisze do data/games.csv. Twoje oceny, statusy i
notatki sa tylko Twoje - dane z API leza obok, w osobnym pliku, laczone po
tytule dopiero przy budowaniu strony. Zly trafiony tytul niczego nie psuje.

Klucz (darmowy, z rawg.io/apidocs) podaje sie w zmiennej RAWG_API_KEY.

Uruchomienie:
    RAWG_API_KEY=... python3 scripts/enrich.py --limit 200
    RAWG_API_KEY=... python3 scripts/enrich.py --retry-unmatched --limit 50
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAMES = ROOT / "data" / "games.csv"
METADATA = ROOT / "data" / "metadata.csv"

API = "https://api.rawg.io/api/games"
USER_AGENT = "video-games-collection/1.0 (+github.com/jackgranatowski/video-games-collection)"

COLUMNS = [
    "title",       # klucz zlaczenia - dokladny tytul z games.csv
    "rawg_id",
    "rawg_slug",
    "rawg_name",   # jak gra nazywa sie w RAWG, do kontroli trafienia
    "released",
    "genres",
    "metacritic",
    "playtime",
    "cover",
    "score",       # 0.00-1.00, podobienstwo tytulow
    "checked",     # data sprawdzenia, zeby nie pytac o to samo w kolko
]

# Ponizej tego progu trafienie uznajemy za niepewne i zapisujemy jako puste.
MATCH_THRESHOLD = 0.82
# Trafienie w rok premiery podnosi wynik - rozroznia remake'i od oryginalow.
YEAR_BONUS = 0.08

# Nawiasy i dopiski, ktorych RAWG nie zna: "(+ DLC)", "(2024) Remake".
NOISE = re.compile(r"\s*[\(\[][^)\]]*[\)\]]", re.UNICODE)
PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def search_title(title: str) -> str:
    """Tytul oczyszczony pod zapytanie do API."""
    cleaned = NOISE.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—:")
    return cleaned or title


def normalize(name: str) -> str:
    """Postac do porownywania: bez interpunkcji, malymi literami."""
    text = NOISE.sub(" ", name.lower())
    text = text.replace("&", " and ")
    text = PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def fetch(url: str, attempts: int = 4) -> dict:
    """GET z ponawianiem przy 429 i bledach serwera."""
    delay = 2.0
    last_error = ""

    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
            if error.code == 401:
                sys.exit("❌ RAWG odrzucil klucz (401). Sprawdz RAWG_API_KEY.")
            if error.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = str(error)

        if attempt < attempts - 1:
            time.sleep(delay)
            delay *= 2

    raise RuntimeError(f"RAWG nie odpowiada: {last_error}")


def best_match(title: str, year: str, results: list[dict]) -> tuple[dict | None, float]:
    best: dict | None = None
    best_score = 0.0

    for candidate in results:
        name = candidate.get("name") or ""
        if not name:
            continue

        score = similarity(title, name)
        released = (candidate.get("released") or "")[:4]
        if year and released:
            if released == year:
                score += YEAR_BONUS
            elif abs(int(released) - int(year)) > 2:
                # Rozjazd wiekszy niz dwa lata to zwykle inna gra o tej nazwie.
                score -= YEAR_BONUS

        if score > best_score:
            best, best_score = candidate, score

    return best, round(min(best_score, 1.0), 2)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(handle)]


def write_metadata(rows: list[dict[str, str]]) -> None:
    rows.sort(key=lambda row: row["title"].lower())
    with METADATA.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dociaga metadane z RAWG.")
    parser.add_argument("--limit", type=int, default=200,
                        help="ile gier sprawdzic w tym przebiegu (domyslnie 200)")
    parser.add_argument("--delay", type=float, default=0.35,
                        help="przerwa miedzy zapytaniami w sekundach")
    parser.add_argument("--retry-unmatched", action="store_true",
                        help="sprobuj ponownie dla gier bez trafienia")
    parser.add_argument("--dry-run", action="store_true",
                        help="pokaz, co zostaloby sprawdzone, bez odpytywania API")
    args = parser.parse_args()

    key = os.environ.get("RAWG_API_KEY", "").strip()
    if not key and not args.dry_run:
        sys.exit(
            "❌ Brak RAWG_API_KEY.\n"
            "   Darmowy klucz: https://rawg.io/apidocs (rejestracja mailem, 20 000 zapytan/mies.)\n"
            "   Lokalnie:  RAWG_API_KEY=xxx python3 scripts/enrich.py\n"
            "   W Actions: Settings -> Secrets and variables -> Actions -> RAWG_API_KEY"
        )

    games = read_csv(GAMES)
    metadata = {row["title"]: row for row in read_csv(METADATA)}

    todo = []
    for game in games:
        title = game["title"]
        known = metadata.get(title)
        if known is None:
            todo.append(game)
        elif args.retry_unmatched and not known["rawg_id"]:
            todo.append(game)

    if not todo:
        print("Wszystkie gry maja juz metadane. Nic do zrobienia.")
        return 0

    batch = todo[: args.limit]
    print(f"Do sprawdzenia: {len(todo)}, w tym przebiegu: {len(batch)}")

    if args.dry_run:
        for game in batch[:20]:
            print(f"  {game['title']}  ->  szukalbym: '{search_title(game['title'])}'")
        if len(batch) > 20:
            print(f"  ... i {len(batch) - 20} wiecej")
        return 0

    today = time.strftime("%Y-%m-%d")
    matched = 0
    unmatched = 0

    for index, game in enumerate(batch, start=1):
        title = game["title"]
        query = urllib.parse.urlencode({
            "key": key,
            "search": search_title(title),
            "page_size": 5,
        })

        try:
            payload = fetch(f"{API}?{query}")
        except RuntimeError as error:
            print(f"\n⚠️  Przerywam po {index - 1} grach: {error}")
            break

        candidate, score = best_match(title, game.get("year", ""), payload.get("results", []))
        row = {column: "" for column in COLUMNS}
        row["title"] = title
        row["checked"] = today
        row["score"] = f"{score:.2f}"

        if candidate and score >= MATCH_THRESHOLD:
            row.update({
                "rawg_id": str(candidate.get("id") or ""),
                "rawg_slug": candidate.get("slug") or "",
                "rawg_name": candidate.get("name") or "",
                "released": (candidate.get("released") or "")[:10],
                "genres": ";".join(g.get("name", "") for g in candidate.get("genres") or []),
                "metacritic": str(candidate.get("metacritic") or ""),
                "playtime": str(candidate.get("playtime") or ""),
                "cover": candidate.get("background_image") or "",
            })
            matched += 1
        else:
            # Zapisujemy nawet nietrafione, zeby nie pytac o nie co tydzien.
            if candidate:
                row["rawg_name"] = candidate.get("name") or ""
            unmatched += 1

        metadata[title] = row

        if index % 25 == 0 or index == len(batch):
            print(f"  {index}/{len(batch)}  trafione: {matched}, nietrafione: {unmatched}")

        time.sleep(args.delay)

    write_metadata(list(metadata.values()))

    total = len(metadata)
    with_data = sum(1 for row in metadata.values() if row["rawg_id"])
    print(
        f"\nZapisano {METADATA.relative_to(ROOT)}: {total} wpisow, "
        f"{with_data} z danymi ({with_data * 100 // max(total, 1)}%)"
    )
    print(f"Pozostalo do sprawdzenia: {max(len(todo) - len(batch), 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
