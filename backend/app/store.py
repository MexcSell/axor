"""SQLite history of per-subnet metrics, used for the 7-day trend charts and 24h smoothing."""
import sqlite3, threading, time

COLS = ("price", "reg_cost", "emission_day", "top_miner", "second_miner", "median_miner", "earning", "volume")

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute(f"""CREATE TABLE IF NOT EXISTS history (
                netuid INTEGER, block INTEGER, ts REAL, {", ".join(c + " REAL" for c in COLS)},
                PRIMARY KEY (netuid, block))""")
            self.db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            self.db.commit()

    def put(self, rows):
        """rows: dicts with netuid, block, ts and any subset of COLS (missing -> NULL, existing kept)."""
        with self.lock:
            for r in rows:
                vals = [r.get(c) for c in COLS]
                self.db.execute(
                    f"""INSERT INTO history (netuid, block, ts, {", ".join(COLS)}) VALUES (?,?,?,{",".join("?" * len(COLS))})
                    ON CONFLICT(netuid, block) DO UPDATE SET {", ".join(f"{c}=COALESCE(excluded.{c},{c})" for c in COLS)}""",
                    [r["netuid"], r["block"], r["ts"], *vals])
            self.db.commit()

    def series(self, since_ts):
        """{netuid: [(ts, {col: val}), ...]} ordered by time."""
        with self.lock:
            cur = self.db.execute(
                f"SELECT netuid, ts, {', '.join(COLS)} FROM history WHERE ts >= ? ORDER BY ts", (since_ts,))
            out = {}
            for row in cur:
                out.setdefault(row[0], []).append((row[1], dict(zip(COLS, row[2:]))))
            return out

    def prune(self, keep_days=30):
        with self.lock:
            self.db.execute("DELETE FROM history WHERE ts < ?", (time.time() - keep_days * 86400,))
            self.db.commit()

    def meta(self, k, v=None):
        with self.lock:
            if v is None:
                r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
                return r[0] if r else None
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))
            self.db.commit()
