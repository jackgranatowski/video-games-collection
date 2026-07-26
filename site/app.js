'use strict';

// Kolejnosc musi zgadzac sie z FIELDS w scripts/build_site.py.
const FIELDS = ['title', 'year', 'status', 'priority', 'owned', 'platforms', 'vr',
  'rating', 'finished_year', 'hype', 'review', 'blog', 'tags', 'notes',
  'genres', 'cover', 'metacritic', 'rawg_slug'];

const IDX = {};
FIELDS.forEach((name, i) => { IDX[name] = i; });

const STATUSES = [
  ['playing', 'Ogrywam'],
  ['want_to_try', 'Chcę spróbować'],
  ['upcoming', 'Przed premierą'],
  ['backlog', 'Do ogrania'],
  ['limbo', 'Limbo'],
  ['completed', 'Ukończone'],
  ['played', 'Ograne'],
  ['not_interested', 'Nie interesuje'],
];

const STATUS_LABEL = Object.fromEntries(STATUSES);
const PRIORITY_LABEL = { high: 'priorytet', normal: 'na pewno', someday: 'kiedyś', skip: 'olewam' };
const VR_LABEL = { yes: 'VR', required: 'VR wymagane', optional: 'VR opcjonalne' };
const REVIEW_LABEL = { todo: 'recenzja do napisania', done: 'recenzja jest' };

// Statusy widoczne na start - lista wykluczen jest ogromna i zaslania resztę.
const DEFAULT_STATUSES = STATUSES.map(([key]) => key).filter((key) => key !== 'not_interested');

const PAGE_SIZE = 60;

const el = (id) => document.getElementById(id);
const state = {
  q: '',
  statuses: new Set(DEFAULT_STATUSES),
  platform: '',
  tag: '',
  genre: '',
  vr: '',
  owned: '',
  priority: '',
  yearFrom: '',
  yearTo: '',
  rating: '',
  sort: 'title',
};

let all = [];
let filtered = [];
let shown = 0;
let observer = null;

/* ---------------- repo / motyw ---------------- */

function repoBase() {
  const host = location.hostname.match(/^([^.]+)\.github\.io$/);
  const path = location.pathname.split('/').filter(Boolean)[0];
  if (host && path) return `https://github.com/${host[1]}/${path}`;
  return 'https://github.com/jackgranatowski/video-games-collection';
}

function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved) document.documentElement.dataset.theme = saved;
  el('theme-toggle').addEventListener('click', () => {
    const current = document.documentElement.dataset.theme
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('theme', next);
  });
}

/* ---------------- stan w adresie URL ---------------- */

function writeHash() {
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  const statuses = [...state.statuses].sort().join(',');
  if (statuses !== [...DEFAULT_STATUSES].sort().join(',')) params.set('status', statuses);
  ['platform', 'tag', 'genre', 'vr', 'owned', 'priority', 'rating'].forEach((key) => {
    if (state[key]) params.set(key, state[key]);
  });
  if (state.yearFrom) params.set('from', state.yearFrom);
  if (state.yearTo) params.set('to', state.yearTo);
  if (state.sort !== 'title') params.set('sort', state.sort);
  const query = params.toString();
  history.replaceState(null, '', query ? `#${query}` : location.pathname);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.toString()) return;
  state.q = params.get('q') || '';
  if (params.has('status')) {
    const list = params.get('status').split(',').filter(Boolean);
    state.statuses = new Set(list);
  }
  ['platform', 'tag', 'genre', 'vr', 'owned', 'priority', 'rating'].forEach((key) => {
    state[key] = params.get(key) || '';
  });
  state.yearFrom = params.get('from') || '';
  state.yearTo = params.get('to') || '';
  state.sort = params.get('sort') || 'title';
}

/* ---------------- filtrowanie ---------------- */

function haystack(game) {
  if (game._h === undefined) {
    game._h = [
      game[IDX.title],
      game[IDX.platforms].join(' '),
      game[IDX.tags].join(' '),
      game[IDX.genres].join(' '),
      game[IDX.notes],
    ].join(' ').toLowerCase();
  }
  return game._h;
}

function matches(game) {
  if (state.statuses.size && !state.statuses.has(game[IDX.status])) return false;

  if (state.q) {
    const text = haystack(game);
    if (!state.q.split(/\s+/).every((word) => text.includes(word))) return false;
  }

  if (state.platform && !game[IDX.platforms].includes(state.platform)) return false;
  if (state.tag && !game[IDX.tags].includes(state.tag)) return false;
  if (state.genre && !game[IDX.genres].includes(state.genre)) return false;
  if (state.owned && game[IDX.owned] !== state.owned) return false;
  if (state.priority && game[IDX.priority] !== state.priority) return false;

  if (state.vr) {
    const vr = game[IDX.vr];
    if (state.vr === 'any') {
      if (!vr || vr === 'no') return false;
    } else if (vr !== state.vr) return false;
  }

  const year = game[IDX.year];
  if (state.yearFrom && (year === null || year < +state.yearFrom)) return false;
  if (state.yearTo && (year === null || year > +state.yearTo)) return false;

  if (state.rating) {
    const rating = game[IDX.rating];
    if (rating === null || rating < +state.rating) return false;
  }

  return true;
}

function compare(a, b) {
  const desc = state.sort.startsWith('-');
  const field = desc ? state.sort.slice(1) : state.sort;
  const x = a[IDX[field]];
  const y = b[IDX[field]];

  if (field === 'title') {
    const result = x.localeCompare(y, 'pl');
    return desc ? -result : result;
  }
  // Puste wartosci zawsze na koncu, niezaleznie od kierunku sortowania.
  if (x === null && y === null) return a[IDX.title].localeCompare(b[IDX.title], 'pl');
  if (x === null) return 1;
  if (y === null) return -1;
  if (x !== y) return desc ? y - x : x - y;
  return a[IDX.title].localeCompare(b[IDX.title], 'pl');
}

/* ---------------- rysowanie ---------------- */

function badge(text, className) {
  const span = document.createElement('span');
  span.className = className;
  span.textContent = text;
  return span;
}

// RAWG serwuje przeskalowane okladki pod /media/resize/<szerokosc>/-/.
// Jesli wariant nie istnieje, onerror wraca do oryginalu.
function thumbnail(url) {
  return url.replace('/media/games/', '/media/resize/420/-/games/');
}

function renderGame(game) {
  const card = document.createElement('article');
  card.className = 'game';

  const cover = game[IDX.cover];
  if (cover) {
    const image = document.createElement('img');
    image.className = 'game-cover';
    image.loading = 'lazy';
    image.decoding = 'async';
    image.alt = '';
    image.src = thumbnail(cover);
    image.addEventListener('error', function onError() {
      // Jedno podejscie do oryginalu, potem chowamy - zadnych petli.
      if (this.src !== cover) this.src = cover;
      else this.remove();
    });
    card.appendChild(image);
  }

  const body = document.createElement('div');
  body.className = 'game-body';

  const head = document.createElement('div');
  head.className = 'game-head';

  const title = document.createElement('div');
  title.className = 'game-title';
  const slug = game[IDX.rawg_slug];
  if (slug) {
    const link = document.createElement('a');
    link.href = `https://rawg.io/games/${slug}`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = game[IDX.title];
    title.appendChild(link);
  } else {
    title.textContent = game[IDX.title];
  }
  if (game[IDX.year] !== null) {
    const year = document.createElement('span');
    year.className = 'game-year';
    year.textContent = game[IDX.year];
    title.appendChild(year);
  }
  head.appendChild(title);

  const status = game[IDX.status];
  head.appendChild(badge(STATUS_LABEL[status] || status, `status-badge s-${status}`));
  body.appendChild(head);

  const meta = document.createElement('div');
  meta.className = 'game-meta';

  if (game[IDX.owned] === 'yes') meta.appendChild(badge('✓ mam', 'owned-mark'));
  game[IDX.platforms].forEach((platform) => meta.appendChild(badge(platform, 'tag platform')));

  const vr = game[IDX.vr];
  if (vr && vr !== 'no') meta.appendChild(badge(VR_LABEL[vr] || 'VR', 'tag vr'));

  if (game[IDX.rating] !== null) {
    meta.appendChild(badge('★'.repeat(game[IDX.rating]), 'rating'));
  }

  const metacritic = game[IDX.metacritic];
  if (metacritic !== null) {
    const level = metacritic >= 75 ? 'good' : metacritic >= 50 ? 'mixed' : 'bad';
    meta.appendChild(badge(`MC ${metacritic}`, `tag metacritic mc-${level}`));
  }
  game[IDX.genres].forEach((genre) => meta.appendChild(badge(genre, 'tag genre')));
  if (game[IDX.finished_year] !== null) {
    meta.appendChild(badge(`ukończone ${game[IDX.finished_year]}`, 'tag'));
  }
  if (game[IDX.hype] !== null) meta.appendChild(badge(`hype ${game[IDX.hype]}/10`, 'tag'));

  const priority = game[IDX.priority];
  if (priority && PRIORITY_LABEL[priority]) {
    meta.appendChild(badge(PRIORITY_LABEL[priority], 'tag'));
  }

  game[IDX.tags].forEach((tag) => meta.appendChild(badge(`#${tag}`, 'tag')));

  const review = game[IDX.review];
  if (REVIEW_LABEL[review]) meta.appendChild(badge(REVIEW_LABEL[review], 'tag'));
  if (game[IDX.blog] === 'yes') meta.appendChild(badge('na blogu', 'tag'));
  if (game[IDX.notes]) meta.appendChild(badge(game[IDX.notes], 'tag'));

  if (meta.childElementCount) body.appendChild(meta);
  card.appendChild(body);
  return card;
}

function renderChunk() {
  const slice = filtered.slice(shown, shown + PAGE_SIZE);
  const fragment = document.createDocumentFragment();
  slice.forEach((game) => fragment.appendChild(renderGame(game)));
  el('results').appendChild(fragment);
  shown += slice.length;
  el('end-note').hidden = shown < filtered.length || filtered.length === 0;
}

function apply() {
  filtered = all.filter(matches).sort(compare);
  shown = 0;
  el('results').replaceChildren();

  const total = filtered.length;
  el('result-count').textContent = total
    ? `${total} ${total === 1 ? 'gra' : 'gier'}`
    : 'Nic nie pasuje do tych filtrów.';

  if (!total) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'Spróbuj poluzować filtry albo wyczyścić wyszukiwanie.';
    el('results').appendChild(empty);
    el('end-note').hidden = true;
  } else {
    renderChunk();
  }

  const active = ['platform', 'tag', 'genre', 'vr', 'owned', 'priority', 'rating', 'yearFrom', 'yearTo']
    .filter((key) => state[key]).length;
  el('filter-count').textContent = active ? `(${active})` : '';

  updateChipCounts();
  writeHash();
}

/* ---------------- statystyki i chipy ---------------- */

function renderStats() {
  const counts = {};
  all.forEach((game) => { counts[game[IDX.status]] = (counts[game[IDX.status]] || 0) + 1; });
  const owned = all.filter((game) => game[IDX.owned] === 'yes').length;
  const vr = all.filter((game) => game[IDX.vr] && game[IDX.vr] !== 'no').length;
  const backlog = (counts.backlog || 0) + (counts.want_to_try || 0) + (counts.limbo || 0);

  const tiles = [
    [all.length, 'gier w bazie'],
    [counts.playing || 0, 'ogrywam'],
    [counts.completed || 0, 'ukończone'],
    [backlog, 'w kolejce'],
    [owned, 'mam na koncie'],
    [vr, 'z VR'],
  ];

  el('stats').replaceChildren(...tiles.map(([value, label]) => {
    const div = document.createElement('div');
    div.className = 'stat';
    const strong = document.createElement('b');
    strong.textContent = value.toLocaleString('pl');
    const span = document.createElement('span');
    span.textContent = label;
    div.append(strong, span);
    return div;
  }));
}

function buildChips() {
  const counts = {};
  all.forEach((game) => { counts[game[IDX.status]] = (counts[game[IDX.status]] || 0) + 1; });

  el('status-chips').replaceChildren(...STATUSES.map(([key, label]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chip';
    button.dataset.status = key;
    button.setAttribute('aria-pressed', state.statuses.has(key));
    button.append(document.createTextNode(label));
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = counts[key] || 0;
    button.appendChild(count);
    button.addEventListener('click', () => {
      if (state.statuses.has(key)) state.statuses.delete(key);
      else state.statuses.add(key);
      button.setAttribute('aria-pressed', state.statuses.has(key));
      apply();
    });
    return button;
  }));
}

function updateChipCounts() {
  document.querySelectorAll('.chip').forEach((chip) => {
    chip.setAttribute('aria-pressed', state.statuses.has(chip.dataset.status));
  });
}

function fillSelect(select, values) {
  values.forEach((value) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

/* ---------------- podpiecie kontrolek ---------------- */

function bind() {
  let timer;
  el('search').addEventListener('input', (event) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = event.target.value.trim().toLowerCase();
      apply();
    }, 150);
  });

  const simple = {
    platform: 'platform', tag: 'tag', genre: 'genre', vr: 'vr', owned: 'owned',
    priority: 'priority', rating: 'rating', sort: 'sort',
  };
  Object.entries(simple).forEach(([id, key]) => {
    el(id).addEventListener('change', (event) => {
      state[key] = event.target.value;
      apply();
    });
  });

  el('year-from').addEventListener('change', (event) => {
    state.yearFrom = event.target.value;
    apply();
  });
  el('year-to').addEventListener('change', (event) => {
    state.yearTo = event.target.value;
    apply();
  });

  el('reset').addEventListener('click', () => {
    state.q = '';
    state.statuses = new Set(DEFAULT_STATUSES);
    ['platform', 'tag', 'genre', 'vr', 'owned', 'priority', 'rating', 'yearFrom', 'yearTo']
      .forEach((key) => { state[key] = ''; });
    state.sort = 'title';
    syncControls();
    apply();
  });

  observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && shown < filtered.length) renderChunk();
  }, { rootMargin: '600px' });
  observer.observe(el('sentinel'));
}

function syncControls() {
  el('search').value = state.q;
  el('platform').value = state.platform;
  el('tag').value = state.tag;
  el('genre').value = state.genre;
  el('vr').value = state.vr;
  el('owned').value = state.owned;
  el('priority').value = state.priority;
  el('rating').value = state.rating;
  el('year-from').value = state.yearFrom;
  el('year-to').value = state.yearTo;
  el('sort').value = state.sort;
}

/* ---------------- start ---------------- */

async function main() {
  initTheme();

  const base = repoBase();
  el('add-link').href = `${base}/issues/new?template=add-game.yml`;
  el('repo-link').href = `${base}/blob/main/data/games.csv`;

  let data;
  try {
    const response = await fetch('games.json');
    if (!response.ok) throw new Error(response.status);
    data = await response.json();
  } catch (error) {
    el('result-count').textContent = `Nie udało się wczytać games.json (${error.message}).`;
    return;
  }

  all = data.games;
  el('generated').textContent = `Dane z ${data.generated}`;

  fillSelect(el('platform'), data.facets.platforms);
  fillSelect(el('tag'), data.facets.tags);
  fillSelect(el('genre'), data.facets.genres || []);

  readHash();
  syncControls();
  renderStats();
  buildChips();
  bind();
  apply();
}

main();
