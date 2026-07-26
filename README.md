# 🎮 Kolekcja gier

Zarządzanie kolekcją gier w całości na GitHubie — bez serwera, bazy danych i hostingu.
Źródłem prawdy jest jeden plik CSV, reszta buduje się sama.

**Strona:** https://jackgranatowski.github.io/video-games-collection/
**Dane:** [`data/games.csv`](data/games.csv) — 5025 gier

---

## Jak to działa

```
data/games.csv  ──►  GitHub Actions  ──►  GitHub Pages (wyszukiwarka + filtry)
      ▲
      │
  Issue Forms (dodaj / zmień grę)  ──►  bot dopisuje wiersz i zamyka zgłoszenie
```

Cztery sposoby na zmianę danych, wszystkie kończą się commitem w `data/games.csv`:

| Chcę… | Jak |
|---|---|
| dodać grę z telefonu | Issue → **➕ Dodaj grę** → wyślij. Bot robi resztę. |
| zmienić jedną rzecz | Issue → **✏️ Zmień grę** → wypełnij tylko to, co się zmienia. |
| poprawić kilkanaście wierszy | Edytuj `data/games.csv` wprost w przeglądarce (ołówek na GitHubie). |
| zrobić większe porządki | Pobierz eksport `.xlsx`, popraw w Excelu, wróć do CSV. |

Po każdej zmianie Actions sprawdza poprawność pliku i przebudowuje stronę. Jeśli coś
jest nie tak — dostajesz czerwony krzyżyk z konkretnym numerem wiersza.

---

## Format danych

Jeden wiersz = jedna gra, 14 kolumn:

| Kolumna | Wartości | Znaczenie |
|---|---|---|
| `title` | tekst | Tytuł. Jedyne pole wymagane. |
| `year` | 1950–2040 | Rok premiery |
| `status` | patrz niżej | Gdzie gra jest w Twoim życiu |
| `priority` | `high` `normal` `someday` `skip` | Jak bardzo się pali |
| `owned` | `yes` `no` | Mam poza abonamentami? |
| `platforms` | `PS5;Steam` | Kilka rozdziel średnikiem |
| `vr` | `no` `yes` `optional` `required` | Wsparcie VR |
| `rating` | 1–5 | Twoja ocena |
| `finished_year` | 1950–2040 | Rok ukończenia |
| `hype` | 1–10 | Jak bardzo się jarasz |
| `review` | `todo` `done` `not_needed` | Stan recenzji |
| `blog` | `yes` `no` | Dodane do bazy na blogu |
| `tags` | `vr;emerytura` | Dowolne etykiety, średnik rozdziela |
| `notes` | tekst | Cokolwiek |

Okładki, gatunki i Metacritic mieszkają osobno w `data/metadata.csv` — patrz sekcja o API.

### Statusy

| Status | Znaczenie | Ile |
|---|---|---:|
| `playing` | Ogrywam teraz (w tym MMO/endless na stałe) | 25 |
| `want_to_try` | Chcę tylko spróbować / sprawdzić | 83 |
| `upcoming` | Przed premierą, do sprawdzenia | 51 |
| `backlog` | Do ogrania | 673 |
| `limbo` | Zainteresowany, ale nie pali się | 103 |
| `completed` | Ukończone / wyczerpane | 610 |
| `played` | Ograne, ale nieukończone | 414 |
| `not_interested` | Nie interesuje mnie | 3066 |

`not_interested` to lista wykluczeń — jest największa, więc na stronie jest domyślnie
ukryta. Jeden klik w chip „Nie interesuje" ją pokazuje.

### Tagi po migracji

`emerytura` (619), `vr` (228), `wrócić` (66), `można-olać` (62), `brak-sprzętu` (33),
`nie-pali-się` (23), `chcę-zagrać` (21), `fabuła` (14), `regularne` i `multiplayer` (12),
`dodatki-do-ogrania` (11), `psvr2` (4), `razem` (1).

Tagi trzymają niuanse, które w arkuszu były nazwą sekcji — np. gra ukończona, do której
chcesz wrócić po trofea, ma `status=completed` i `tags=wrócić`.

---

## Metadane z API (RAWG)

Okładki, gatunki, oceny Metacritic i daty premier dociągane są z
[RAWG](https://rawg.io/apidocs) — darmowe 20 000 zapytań miesięcznie, klucz z rejestracji
mailem. Wystarczy na pełne pokrycie 5025 gier z dużym zapasem.

**API nigdy nie pisze do `data/games.csv`.** Dane z RAWG lądują w osobnym
`data/metadata.csv` i są łączone z Twoimi po tytule dopiero przy budowaniu strony.
Źle trafiony tytuł psuje najwyżej okładkę — Twoje oceny, statusy i notatki są nietykalne.

### Włączenie

1. Weź darmowy klucz na https://rawg.io/apidocs
2. Settings → Secrets and variables → Actions → New secret → nazwa **`RAWG_API_KEY`**
3. Actions → **Wzbogać dane z RAWG** → Run workflow

Bez sekretu workflow kończy się ostrzeżeniem i nic nie robi — strona działa jak wcześniej,
po prostu bez okładek.

### Jak dobierane są trafienia

Tytuł idzie do wyszukiwarki RAWG po oczyszczeniu z dopisków (`Elden Ring (+ Shadow of
the erdtree)` → `Elden Ring`). Z pięciu kandydatów wybierany jest najpodobniejszy, a rok
premiery z Twojego arkusza rozstrzyga remake'i — `Until Dawn` 2024 nie zostanie podmienione
na wydanie z 2015. Poniżej progu podobieństwa **0.82** wpis zostaje pusty i oznaczony jako
sprawdzony, żeby nie odpytywać o niego co tydzień. `Kangurek Kao` nie zostanie uznany za
`Kao the Kangaroo` — lepiej brak danych niż złe dane.

Kolumna `score` w `metadata.csv` pokazuje pewność trafienia, a `rawg_name` — pod jaką
nazwą gra została znaleziona. Łatwo przejrzeć i poprawić ręcznie.

```bash
RAWG_API_KEY=... python3 scripts/enrich.py --limit 200    # kolejna porcja
RAWG_API_KEY=... python3 scripts/enrich.py --retry-unmatched --limit 50
python3 scripts/enrich.py --dry-run                       # co by poszło do API
```

Workflow chodzi też sam w każdą niedzielę po 300 gier.

---

## Skrypty

Wymagają Pythona 3.11+; do arkuszy `pip install openpyxl`.

```bash
python3 scripts/validate.py          # sprawdź CSV (używane przez CI)
python3 scripts/validate.py --fix    # posortuj alfabetycznie i zapisz
python3 scripts/build_site.py        # zbuduj stronę do _site/
python3 scripts/export_xlsx.py       # CSV -> Kolekcja_gier_export.xlsx
python3 scripts/enrich.py --dry-run  # co poszłoby do RAWG
python3 scripts/migrate_xlsx.py      # jednorazowa migracja z oryginalnego arkusza

python3 -m http.server -d _site 8000 # podgląd strony lokalnie
```

`scripts/issue_to_csv.py` uruchamia bot — ręcznie nie jest potrzebny.

---

## Uruchomienie u siebie

1. **Włącz GitHub Pages:** Settings → Pages → Source: **GitHub Actions**.
2. **Pozwól Actions na zapis:** Settings → Actions → General → Workflow permissions →
   **Read and write permissions**. Bez tego bot nie dopisze gry ze zgłoszenia.
3. Zrób dowolny commit do `main` — strona zbuduje się sama.

Repo publiczne = Pages za darmo. Przy prywatnym repo Pages wymaga płatnego planu;
formularze, walidacja i eksport działają tak samo.

---

## Co strona potrafi

- Szukanie po tytule, platformie, tagach i notatkach (wiele słów naraz)
- Filtry: status, platforma, tag, gatunek, VR, posiadanie, priorytet, zakres lat, ocena
- Sortowanie po tytule, roku, ocenie, Metacriticu, hype i roku ukończenia
- Okładki, gatunki i oceny Metacritic z RAWG; tytuł linkuje do strony gry
- Stan filtrów zapisuje się w adresie — link do „wszystkie gry VR, których nie mam"
  można wysłać albo dodać do zakładek
- Motyw jasny/ciemny, działa na telefonie
- Wszystko liczy się w przeglądarce, zero backendu

---

## Znane rzeczy do posprzątania

Walidator wypisuje je jako ostrzeżenia — nie blokują niczego:

- **~90 zdublowanych tytułów** — ta sama gra trafiła do dwóch sekcji arkusza,
  np. raz jako „do ogrania", raz jako „nie interesuje". Do rozstrzygnięcia po jednej.
- **Rzadkie platformy** — `PSS` (8×) to prawdopodobnie PS Store albo literówka od PS5,
  a `Prime` / `Prime Gaming` / `Amazon Prime` to być może to samo. Zostawione bez
  zmian, bo tylko Ty wiesz, co miałeś na myśli.
- **Braki w danych** — rok premiery jest w 1920 z 5025 wierszy, ocena w 43.
  Uzupełniane w miarę potrzeb, nic od tego nie zależy.

Oryginalny arkusz leży w [`data/archive/`](data/archive/) — nic nie przepadło.
