#!/usr/bin/env python3
"""Dociaga metadane gier do data/metadata.csv z RAWG, a w drugiej kolejnosci z IGDB.

Zasada: ten skrypt NIGDY nie pisze do data/games.csv. Twoje oceny, statusy i
notatki sa tylko Twoje - dane z API leza obok, w osobnym pliku, laczone po
tytule dopiero przy budowaniu strony. Zly trafiony tytul niczego nie psuje.

Zrodla probowane po kolei, pierwsze pewne trafienie wygrywa:
  1. RAWG  - RAWG_API_KEY            (darmowy klucz z rawg.io/apidocs)
  2. IGDB  - IGDB_CLIENT_ID + IGDB_CLIENT_SECRET  (darmowe z dev.twitch.tv)

Wystarczy skonfigurowac jedno z nich. Brakujace zrodlo jest po cichu pomijane.

Uruchomienie:
    RAWG_API_KEY=... python3 scripts/enrich.py --limit 200
    python3 scripts/enrich.py --only igdb --retry-unmatched --limit 50
    python3 scripts/enrich.py --dry-run
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

USER_AGENT = "video-games-collection/1.0 (+github.com/jackgranatowski/video-games-collection)"

COLUMNS = [
    "title",        # klucz zlaczenia - dokladny tytul z games.csv
    "source",       # rawg albo igdb
    "source_id",
    "source_slug",
    "source_name",  # jak gra nazywa sie u zrodla, do kontroli trafienia
    "released",
    "genres",
    "metacritic",
    "playtime",     # srednia dlugosc w godzinach
    "cover",
    "score",        # 0.00-1.00, pewnosc dopasowania tytulu
    "checked",      # data sprawdzenia, zeby nie pytac o to samo w kolko
]

# Ponizej tego progu trafienie uznajemy za niepewne i zapisujemy jako puste.
MATCH_THRESHOLD = 0.82
# Trafienie w rok premiery podnosi wynik - rozroznia remake'i od oryginalow.
YEAR_BONUS = 0.08

# Nawiasy i dopiski, ktorych bazy nie znaja: "(+ DLC)", "(2024) Remake".
NOISE = re.compile(r"\s*[\(\[][^)\]]*[\)\]]", re.UNICODE)
PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


# --------------------------------------------------------------------------
# porownywanie tytulow
# --------------------------------------------------------------------------

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


def best_match(title: str, year: str, candidates: list[dict]) -> tuple[dict | None, float]:
    """Najlepszy kandydat i jego wynik. Rok premiery rozstrzyga remake'i."""
    best: dict | None = None
    best_score = 0.0

    for candidate in candidates:
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


# --------------------------------------------------------------------------
# warstwa HTTP
# --------------------------------------------------------------------------

def request(url: str, *, data: bytes | None = None, headers: dict | None = None,
            attempts: int = 4) -> dict | list:
    """GET/POST z ponawianiem przy 429 i bledach serwera."""
    delay = 2.0
    last_error = ""

    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"
            if error.code in (401, 403):
                raise PermissionError(f"{url.split('?')[0]} odrzucil dane logowania ({error.code})")
            if error.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = str(error)

        if attempt < attempts - 1:
            time.sleep(delay)
            delay *= 2

    raise RuntimeError(f"brak odpowiedzi: {last_error}")


# --------------------------------------------------------------------------
# zrodla danych
# --------------------------------------------------------------------------

class Rawg:
    """RAWG: 20 000 zapytan miesiecznie, klucz z rawg.io/apidocs."""

    name = "rawg"
    delay = 0.35
    url_template = "https://rawg.io/games/{slug}"

    def __init__(self) -> None:
        self.key = os.environ.get("RAWG_API_KEY", "").strip()

    def available(self) -> bool:
        return bool(self.key)

    def why_unavailable(self) -> str:
        return "brak RAWG_API_KEY (darmowy klucz: https://rawg.io/apidocs)"

    def search(self, title: str) -> list[dict]:
        query = urllib.parse.urlencode({
            "key": self.key,
            "search": search_title(title),
            "page_size": 5,
        })
        payload = request(f"https://api.rawg.io/api/games?{query}")
        return [self.parse(item) for item in payload.get("results", [])]

    @staticmethod
    def parse(item: dict) -> dict:
        return {
            "id": str(item.get("id") or ""),
            "slug": item.get("slug") or "",
            "name": item.get("name") or "",
            "released": (item.get("released") or "")[:10],
            "genres": ";".join(g.get("name", "") for g in item.get("genres") or []),
            "metacritic": str(item.get("metacritic") or ""),
            "playtime": str(item.get("playtime") or ""),
            "cover": item.get("background_image") or "",
        }


class Igdb:
    """IGDB: bez limitu miesiecznego, 4 zapytania/s. Klucz z dev.twitch.tv."""

    name = "igdb"
    delay = 0.30
    url_template = "https://www.igdb.com/games/{slug}"

    FIELDS = ("fields name,slug,first_release_date,genres.name,"
              "aggregated_rating,cover.image_id;")

    def __init__(self) -> None:
        self.client_id = os.environ.get("IGDB_CLIENT_ID", "").strip()
        self.secret = os.environ.get("IGDB_CLIENT_SECRET", "").strip()
        self.token = ""

    def available(self) -> bool:
        return bool(self.client_id and self.secret)

    def why_unavailable(self) -> str:
        return "brak IGDB_CLIENT_ID / IGDB_CLIENT_SECRET (darmowe: https://dev.twitch.tv/console/apps)"

    def authenticate(self) -> None:
        if self.token:
            return
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.secret,
            "grant_type": "client_credentials",
        })
        payload = request(f"https://id.twitch.tv/oauth2/token?{query}", data=b"")
        self.token = payload.get("access_token", "")
        if not self.token:
            raise PermissionError("Twitch nie zwrocil tokenu dla IGDB")

    def search(self, title: str) -> list[dict]:
        self.authenticate()
        # Apicalypse: zapytanie idzie w ciele jako zwykly tekst.
        term = search_title(title).replace('"', '\\"')
        body = f'search "{term}"; {self.FIELDS} limit 5;'.encode("utf-8")
        payload = request(
            "https://api.igdb.com/v4/games",
            data=body,
            headers={
                "Client-ID": self.client_id,
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "text/plain",
            },
        )
        return [self.parse(item) for item in payload]

    @staticmethod
    def parse(item: dict) -> dict:
        released = ""
        if item.get("first_release_date"):
            released = time.strftime("%Y-%m-%d", time.gmtime(item["first_release_date"]))

        cover = ""
        image_id = (item.get("cover") or {}).get("image_id")
        if image_id:
            cover = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"

        rating = item.get("aggregated_rating")
        return {
            "id": str(item.get("id") or ""),
            "slug": item.get("slug") or "",
            "name": item.get("name") or "",
            "released": released,
            "genres": ";".join(g.get("name", "") for g in item.get("genres") or []),
            # aggregated_rating to srednia ocen krytykow 0-100, nie sam Metacritic,
            # ale ta sama skala - trzymamy w jednej kolumnie.
            "metacritic": str(round(rating)) if rating else "",
            "playtime": "",  # IGDB podaje to osobnym endpointem, nie dociagamy
            "cover": cover,
        }


PROVIDERS = {"rawg": Rawg, "igdb": Igdb}


# --------------------------------------------------------------------------
# wejscie/wyjscie
# --------------------------------------------------------------------------

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
    parser = argparse.ArgumentParser(description="Dociaga metadane gier z RAWG i IGDB.")
    parser.add_argument("--limit", type=int, default=200,
                        help="ile gier sprawdzic w tym przebiegu (domyslnie 200)")
    parser.add_argument("--only", choices=sorted(PROVIDERS),
                        help="uzyj tylko tego zrodla")
    parser.add_argument("--retry-unmatched", action="store_true",
                        help="sprobuj ponownie dla gier bez trafienia")
    parser.add_argument("--dry-run", action="store_true",
                        help="pokaz, co zostaloby sprawdzone, bez odpytywania API")
    args = parser.parse_args()

    wanted = [args.only] if args.only else ["rawg", "igdb"]
    providers = [PROVIDERS[name]() for name in wanted]
    active = [p for p in providers if p.available()]

    for provider in providers:
        state = "gotowe" if provider.available() else f"pominiete - {provider.why_unavailable()}"
        print(f"  {provider.name}: {state}")

    if not active and not args.dry_run:
        sys.exit(
            "\n❌ Zadne zrodlo nie jest skonfigurowane.\n"
            "   RAWG: https://rawg.io/apidocs -> sekret RAWG_API_KEY\n"
            "   IGDB: https://dev.twitch.tv/console/apps -> sekrety IGDB_CLIENT_ID i IGDB_CLIENT_SECRET"
        )

    games = read_csv(GAMES)
    metadata = {row["title"]: row for row in read_csv(METADATA)}

    todo = []
    for game in games:
        known = metadata.get(game["title"])
        if known is None:
            todo.append(game)
        elif args.retry_unmatched and not known.get("source_id"):
            todo.append(game)

    if not todo:
        print("\nWszystkie gry maja juz metadane. Nic do zrobienia.")
        return 0

    batch = todo[: args.limit]
    print(f"\nDo sprawdzenia: {len(todo)}, w tym przebiegu: {len(batch)}")

    if args.dry_run:
        for game in batch[:20]:
            print(f"  {game['title']}  ->  szukalbym: '{search_title(game['title'])}'")
        if len(batch) > 20:
            print(f"  ... i {len(batch) - 20} wiecej")
        return 0

    today = time.strftime("%Y-%m-%d")
    found: dict[str, int] = {p.name: 0 for p in active}
    unmatched = 0

    for index, game in enumerate(batch, start=1):
        title = game["title"]
        row = {column: "" for column in COLUMNS}
        row["title"] = title
        row["checked"] = today

        best_overall: tuple[dict, float, object] | None = None

        for provider in list(active):
            try:
                candidates = provider.search(title)
            except PermissionError as error:
                print(f"\n⚠️  Wylaczam {provider.name}: {error}")
                active.remove(provider)
                continue
            except RuntimeError as error:
                print(f"\n⚠️  {provider.name} nie odpowiada ({error}) - pomijam te gre")
                continue

            candidate, score = best_match(title, game.get("year", ""), candidates)
            if candidate and score >= MATCH_THRESHOLD:
                best_overall = (candidate, score, provider)
                break  # pierwsze pewne trafienie wygrywa
            if candidate and (best_overall is None or score > best_overall[1]):
                best_overall = (candidate, score, provider)

            time.sleep(provider.delay)

        if not active:
            print("⚠️  Zadne zrodlo nie odpowiada - przerywam.")
            break

        if best_overall:
            candidate, score, provider = best_overall
            row["score"] = f"{score:.2f}"
            row["source_name"] = candidate["name"]
            if score >= MATCH_THRESHOLD:
                row["source"] = provider.name
                row["source_id"] = candidate["id"]
                row["source_slug"] = candidate["slug"]
                row["released"] = candidate["released"]
                row["genres"] = candidate["genres"]
                row["metacritic"] = candidate["metacritic"]
                row["playtime"] = candidate["playtime"]
                row["cover"] = candidate["cover"]
                found[provider.name] = found.get(provider.name, 0) + 1
            else:
                # Zapisujemy nawet nietrafione, zeby nie pytac o nie co tydzien.
                unmatched += 1
        else:
            row["score"] = "0.00"
            unmatched += 1

        metadata[title] = row

        if index % 25 == 0 or index == len(batch):
            summary = ", ".join(f"{name}: {count}" for name, count in found.items())
            print(f"  {index}/{len(batch)}  {summary}, bez trafienia: {unmatched}")

    write_metadata(list(metadata.values()))

    total = len(metadata)
    with_data = sum(1 for row in metadata.values() if row.get("source_id"))
    print(
        f"\nZapisano {METADATA.relative_to(ROOT)}: {total} wpisow, "
        f"{with_data} z danymi ({with_data * 100 // max(total, 1)}%)"
    )
    print(f"Pozostalo do sprawdzenia: {max(len(todo) - len(batch), 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
