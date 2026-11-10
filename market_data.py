"""
market_data.py
Daily price history from Massive (api.massive.com), with a disk cache and a rate limiter.

Stocks Basic allows 5 calls a minute and serves end-of-day bars, so every ticker is fetched at most
once per trading day and kept on disk. Requests that need an uncached ticker either wait briefly for
a free call or return "still loading" while a background worker fetches it. Nothing here estimates or
simulates a price: a ticker without data is reported as missing.

Environment:
  MASSIVE_API_KEY        required
  MASSIVE_CALLS_PER_MIN  default 5 (Stocks Basic). Set 0 on Starter or above to remove the limiter.
  CACHE_DIR              default <temp>/wolf_cache. Point it at a Railway volume so the cache survives deploys.
"""
import datetime as dt
import json
import os
import queue
import tempfile
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    import fcntl                      # Linux (Railway). Windows falls back to an in-process lock.
except ImportError:
    fcntl = None

API = "https://api.massive.com"
ET = ZoneInfo("America/New_York")
HISTORY_DAYS = 400                    # calendar days fetched: one year of returns plus a buffer
RECHECK_HOURS = 6                     # how long a fetch that found no newer bar is trusted (holidays)


def _key():
    return os.environ.get("MASSIVE_API_KEY", "").strip()


def _calls_per_min():
    raw = os.environ.get("MASSIVE_CALLS_PER_MIN", "").strip()
    return int(raw) if raw else 5


CACHE_DIR = Path(os.environ.get("CACHE_DIR", "").strip() or Path(tempfile.gettempdir()) / "wolf_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
_LIMIT_FILE = CACHE_DIR / "_calls.json"
_LOCK_FILE = CACHE_DIR / "_calls.lock"
_thread_lock = threading.Lock()
_mem: dict = {}


class MassiveError(Exception):
    pass


class RateLimited(MassiveError):
    pass


def massive_symbol(ticker: str) -> str:
    return ticker.upper().replace("/", ".")


# ── Rate limiter, shared across gunicorn workers through a locked file ────────────────────────────

class _FileLock:
    def __enter__(self):
        _thread_lock.acquire()
        if fcntl:
            self.f = open(_LOCK_FILE, "a+")
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if fcntl:
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()
        _thread_lock.release()


def _acquire(wait_max: float) -> bool:
    limit = _calls_per_min()
    if limit <= 0:
        return True
    deadline = time.time() + wait_max
    while True:
        with _FileLock():
            now = time.time()
            try:
                stamps = [s for s in json.loads(_LIMIT_FILE.read_text()) if now - s < 60]
            except (FileNotFoundError, ValueError):
                stamps = []
            if len(stamps) < limit:
                stamps.append(now)
                _LIMIT_FILE.write_text(json.dumps(stamps))
                return True
            wait = 60 - (now - min(stamps)) + 0.05
        if now + wait > deadline:
            return False
        time.sleep(wait)


def calls_last_minute() -> int:
    try:
        now = time.time()
        return sum(1 for s in json.loads(_LIMIT_FILE.read_text()) if now - s < 60)
    except (FileNotFoundError, ValueError):
        return 0


def _get(path: str, params: dict, wait_max: float) -> dict:
    if not _key():
        raise MassiveError("MASSIVE_API_KEY is not set. Add it in Railway → Variables.")
    for attempt in range(2):
        if not _acquire(wait_max):
            raise RateLimited(path)
        r = requests.get(API + path, params={**params, "apiKey": _key()}, timeout=20)
        if r.status_code == 429 and attempt == 0:
            time.sleep(12)
            continue
        if r.status_code in (401, 403):
            raise MassiveError(f"Massive refused the request (HTTP {r.status_code}). Check the key and plan.")
        if r.status_code == 429:
            raise RateLimited(path)
        r.raise_for_status()
        return r.json()
    raise RateLimited(path)


# ── Freshness ─────────────────────────────────────────────────────────────────────────────────

def expected_last_session(now: dt.datetime | None = None) -> dt.date:
    """The most recent weekday whose end-of-day bar should be published (after 5 pm ET)."""
    now = now or dt.datetime.now(ET)
    d = now.date()
    if d.weekday() >= 5 or now.time() < dt.time(17, 0):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _fresh(entry: dict) -> bool:
    bars = entry.get("bars") or []
    if bars and bars[-1][0] >= expected_last_session().isoformat():
        return True
    fetched = dt.datetime.fromisoformat(entry["fetched_at"])
    return dt.datetime.now(ET) - fetched < dt.timedelta(hours=RECHECK_HOURS)


def _path(ticker):
    return CACHE_DIR / f"bars_{massive_symbol(ticker).replace('.', '_')}.json"


def _load(ticker):
    if ticker in _mem:
        return _mem[ticker]
    try:
        entry = json.loads(_path(ticker).read_text())
        _mem[ticker] = entry
        return entry
    except (FileNotFoundError, ValueError):
        return None


def _fetch(ticker: str, wait_max: float) -> dict:
    today = dt.datetime.now(ET).date()
    start = today - dt.timedelta(days=HISTORY_DAYS)
    body = _get(f"/v2/aggs/ticker/{massive_symbol(ticker)}/range/1/day/{start}/{today}",
                {"adjusted": "true", "sort": "asc", "limit": 50000}, wait_max)
    bars = []
    for b in body.get("results") or []:
        day = dt.datetime.fromtimestamp(b["t"] / 1000, ET).date().isoformat()
        bars.append([day, float(b["c"])])
    entry = {"ticker": ticker, "fetched_at": dt.datetime.now(ET).isoformat(timespec="seconds"), "bars": bars}
    _path(ticker).write_text(json.dumps(entry))
    _mem[ticker] = entry
    print(f"[massive] {ticker}: {len(bars)} daily bars, last {bars[-1][0] if bars else 'none'}")
    return entry


def closes(ticker: str, wait_max: float = 15) -> list:
    """[[date, close], ...] oldest first. Raises RateLimited when no call is free and nothing is cached."""
    entry = _load(ticker)
    if entry and _fresh(entry):
        return entry["bars"]
    try:
        return _fetch(ticker, wait_max)["bars"]
    except RateLimited:
        if entry:                     # yesterday's real bars beat no bars; refresh in the background
            enqueue([ticker])
            return entry["bars"]
        raise


def get_many(tickers: list, budget_s: float = 20) -> tuple[dict, list]:
    """Fetches what it can within the time budget. Returns ({ticker: bars}, [tickers still loading])."""
    out, pending = {}, []
    deadline = time.time() + budget_s
    for t in dict.fromkeys(tickers):
        try:
            out[t] = closes(t, wait_max=max(0.0, deadline - time.time()))
        except RateLimited:
            pending.append(t)
    if pending:
        enqueue(pending)
    return out, pending


def eta_seconds(n_pending: int) -> int:
    limit = _calls_per_min()
    return 0 if limit <= 0 else int(60 * (n_pending / limit + 1))


# ── Background worker ─────────────────────────────────────────────────────────────────────────

_queue: "queue.Queue[str]" = queue.Queue()
_queued: set = set()
_worker_started = False


def _worker():
    while True:
        t = _queue.get()
        try:
            entry = _load(t)
            if not (entry and _fresh(entry)):
                _fetch(t, wait_max=120)
        except Exception as ex:
            print(f"[massive] background fetch {t} failed: {ex}")
        finally:
            _queued.discard(t)


def enqueue(tickers: list):
    global _worker_started
    if not _worker_started:
        threading.Thread(target=_worker, daemon=True).start()
        _worker_started = True
    for t in tickers:
        if t not in _queued:
            _queued.add(t)
            _queue.put(t)


def start_prefetch(tickers: list):
    """Warms the cache once per process start. Only one gunicorn worker does it, through a file lock."""
    if not _key():
        print("[massive] MASSIVE_API_KEY not set, skipping prefetch")
        return
    if fcntl:
        f = open(CACHE_DIR / "_prefetch.lock", "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return
        globals()["_prefetch_lock_handle"] = f     # held for the life of the process
    stale = [t for t in dict.fromkeys(tickers) if not ((e := _load(t)) and _fresh(e))]
    print(f"[massive] prefetching {len(stale)} of {len(tickers)} tickers")
    enqueue(stale)


# ── Market banner: one call returns every US stock for a date ─────────────────────────────────

def grouped_daily(day: dt.date, wait_max: float = 5) -> dict:
    path = CACHE_DIR / f"grouped_{day.isoformat()}.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        pass
    body = _get(f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}", {"adjusted": "true"}, wait_max)
    rows = {r["T"]: {"o": r.get("o"), "c": r.get("c")} for r in body.get("results") or []}
    if rows or day < expected_last_session():      # an empty past date is a holiday: cache that too
        path.write_text(json.dumps(rows))
    return rows


def last_two_sessions(wait_max: float = 8) -> list[tuple[dt.date, dict]]:
    found, d = [], expected_last_session()
    for _ in range(8):
        if d.weekday() < 5:
            rows = grouped_daily(d, wait_max)
            if rows:
                found.append((d, rows))
                if len(found) == 2:
                    break
        d -= dt.timedelta(days=1)
    return found


def cache_status() -> list[dict]:
    out = []
    for p in sorted(CACHE_DIR.glob("bars_*.json")):
        try:
            e = json.loads(p.read_text())
        except ValueError:
            continue
        bars = e.get("bars") or []
        out.append({"ticker": e.get("ticker"), "n": len(bars), "first": bars[0][0] if bars else None,
                    "last": bars[-1][0] if bars else None, "fetched_at": e.get("fetched_at"), "fresh": _fresh(e)})
    return out


# ── Risk-free rate: latest 3-month Treasury yield, refreshed once a day ───────────────────────

def risk_free(wait_max: float = 10) -> tuple[float, str]:
    """(rate as a decimal, description). Uses yesterday's cached yield if today's fetch is not possible."""
    path = CACHE_DIR / "treasury_3m.json"
    try:
        cached = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        cached = None
    today = dt.datetime.now(ET).date().isoformat()
    if cached and cached.get("checked") == today:
        return cached["rate"], f"3-month Treasury, {cached['date']}"
    try:
        body = _get("/fed/v1/treasury-yields", {"sort": "date.desc", "limit": 1}, wait_max)
        row = (body.get("results") or [{}])[0]
        y = row.get("yield_3_month")
        if y is not None:
            rate = float(y) / 100.0 if float(y) > 1.0 else float(y)    # published in percent
            path.write_text(json.dumps({"rate": rate, "date": row.get("date"), "checked": today}))
            return rate, f"3-month Treasury, {row.get('date')}"
    except MassiveError as ex:
        print(f"[massive] treasury fetch failed: {ex}")
    if cached:
        return cached["rate"], f"3-month Treasury, {cached['date']} (cached)"
    raise MassiveError("Could not load the 3-month Treasury yield from Massive.")
