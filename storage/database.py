"""
SIA-TradeX: Database & State Storage
SQLite engine configured with Write-Ahead Logging (WAL) for thread-safe, corruption-proof persistence.
"""

import sqlite3
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from config.settings import settings
from core.models import TradeRecord


class Database:
    def __init__(self, db_path: str = settings.DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for high concurrency and zero lockup
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                exit REAL NOT NULL,
                pnl REAL NOT NULL,
                reason TEXT NOT NULL,
                sources TEXT,
                score INTEGER,
                ai_reason TEXT,
                equity REAL,
                profit_protected INTEGER DEFAULT 0,
                live INTEGER DEFAULT 0,
                leverage INTEGER DEFAULT 3,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                balance REAL NOT NULL,
                equity REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signals_history (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                score INTEGER NOT NULL,
                source TEXT NOT NULL,
                reason TEXT,
                executed INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_income (
                date TEXT PRIMARY KEY,
                realized_income REAL NOT NULL,
                total_trades INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                losses INTEGER NOT NULL,
                win_rate REAL NOT NULL,
                profit_protected_wins INTEGER NOT NULL,
                ending_equity REAL NOT NULL,
                ending_balance REAL NOT NULL,
                cumulative_income REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(created_at);
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_equity_created ON equity_snapshots(created_at);
            CREATE INDEX IF NOT EXISTS idx_daily_income_date ON daily_income(date);
            """)

        # Perform initial daily income calculation & Excel sync
        self._rebuild_daily_income()

    def _rebuild_daily_income(self):
        """Aggregates all recorded trades by UTC date into the daily_income table."""
        try:
            with self._get_connection() as conn:
                trades = conn.execute("""
                SELECT timestamp, pnl, profit_protected, equity, created_at
                FROM trades ORDER BY created_at ASC
                """).fetchall()

            if not trades:
                return

            days: Dict[str, List[Any]] = {}
            for t in trades:
                ts = str(t["timestamp"])
                d_key = ts[:10] if len(ts) >= 10 else datetime.fromtimestamp(t["created_at"]).strftime("%Y-%m-%d")
                days.setdefault(d_key, []).append(t)

            cum_pnl = 0.0
            with self._get_connection() as conn:
                for d_str in sorted(days.keys()):
                    day_trades = days[d_str]
                    d_pnl = sum(r["pnl"] for r in day_trades)
                    cum_pnl += d_pnl
                    wins = sum(1 for r in day_trades if r["pnl"] > 0)
                    losses = sum(1 for r in day_trades if r["pnl"] < 0)
                    total = len(day_trades)
                    wr = (wins / total * 100.0) if total > 0 else 0.0
                    pp_wins = sum(1 for r in day_trades if r["profit_protected"] and r["pnl"] >= 0)
                    latest_eq = float(day_trades[-1]["equity"]) if day_trades[-1]["equity"] else 1000.0

                    conn.execute("""
                    INSERT OR REPLACE INTO daily_income (
                        date, realized_income, total_trades, wins, losses, win_rate,
                        profit_protected_wins, ending_equity, ending_balance,
                        cumulative_income, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        d_str, round(d_pnl, 2), total, wins, losses, round(wr, 1),
                        pp_wins, round(latest_eq, 2), round(latest_eq, 2),
                        round(cum_pnl, 2), time.time()
                    ))
        except Exception:
            pass

    def record_trade(self, trade: TradeRecord) -> str:
        trade_id = trade.id or f"{trade.symbol}_{int(time.time()*1000)}"
        now_ts = time.time()
        with self._get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO trades (
                id, timestamp, symbol, direction, entry, exit, pnl,
                reason, sources, score, ai_reason, equity, profit_protected,
                live, leverage, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, trade.timestamp, trade.symbol, trade.direction,
                trade.entry, trade.exit, trade.pnl, trade.reason,
                json.dumps(trade.sources), trade.score, trade.ai_reason,
                trade.equity, 1 if trade.profit_protected else 0,
                1 if trade.live else 0, trade.leverage, now_ts
            ))

        # Update daily income ledger in DB and sync Excel workbook
        ts_str = str(trade.timestamp)
        d_key = ts_str[:10] if len(ts_str) >= 10 else datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d")
        self._rebuild_daily_income()
        self.sync_excel_ledger()

        return trade_id

    def record_equity_snapshot(self, balance: float, equity: float, unrealized_pnl: float, open_positions: int):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO equity_snapshots (
                timestamp, balance, equity, unrealized_pnl, open_positions, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """, (now_str, balance, equity, unrealized_pnl, open_positions, time.time()))

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT * FROM trades ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("sources"):
                    try:
                        d["sources"] = json.loads(d["sources"])
                    except Exception:
                        d["sources"] = []
                results.append(d)
            return results

    def get_all_trades(self) -> List[Dict[str, Any]]:
        """Returns all trades ordered by timestamp ascending for comprehensive reporting."""
        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT * FROM trades ORDER BY created_at ASC
            """).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("sources"):
                    try:
                        d["sources"] = json.loads(d["sources"])
                    except Exception:
                        d["sources"] = []
                results.append(d)
            return results

    def get_all_daily_income(self) -> List[Dict[str, Any]]:
        """Returns all daily income records from the database ordered by date ascending."""
        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT * FROM daily_income ORDER BY date ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def sync_excel_ledger(self) -> bool:
        """Synchronizes all SQLite trades and daily income data to the multi-tab Excel workbook."""
        try:
            from storage.excel_ledger import excel_ledger
            all_trades = self.get_all_trades()
            all_daily = self.get_all_daily_income()
            snaps = self.get_equity_history(limit=1)
            bal = float(snaps[-1]["balance"]) if snaps else float(settings.PAPER_STARTING_BALANCE)
            eq = float(snaps[-1]["equity"]) if snaps else float(settings.PAPER_STARTING_BALANCE)
            return excel_ledger.sync_ledger(all_trades, all_daily, bal, eq)
        except Exception:
            return False

    def get_equity_history(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT timestamp, balance, equity, unrealized_pnl, open_positions, created_at
            FROM equity_snapshots ORDER BY created_at ASC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_daily_metrics(self) -> Dict[str, Any]:
        now_utc = datetime.utcnow()
        start_of_day_utc = datetime(now_utc.year, now_utc.month, now_utc.day, 0, 0, 0).timestamp()
        today_prefix = now_utc.strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT pnl, profit_protected FROM trades WHERE created_at >= ?
            """, (start_of_day_utc,)).fetchall()
            
            pnl_sum = sum(r["pnl"] for r in rows)
            wins = sum(1 for r in rows if r["pnl"] > 0)
            losses = sum(1 for r in rows if r["pnl"] < 0)
            pp_wins = sum(1 for r in rows if r["profit_protected"] and r["pnl"] >= 0)
            total = wins + losses
            wr = (wins / total * 100) if total > 0 else 0.0

            return {
                "date": today_prefix,
                "pnl": round(pnl_sum, 2),
                "wins": wins,
                "losses": losses,
                "trades_count": total,
                "win_rate": round(wr, 1),
                "profit_protected_wins": pp_wins
            }

    def set_state(self, key: str, value: Any):
        val_str = json.dumps(value) if not isinstance(value, str) else value
        with self._get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)
            """, (key, val_str, time.time()))

    def get_state(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return row["value"]

    def clear_all_trades(self):
        """Clears all trades, daily income, equity snapshots, and signal history for a clean start."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM trades;")
            conn.execute("DELETE FROM daily_income;")
            conn.execute("DELETE FROM equity_snapshots;")
            conn.execute("DELETE FROM signals_history;")
        self.sync_excel_ledger()

db = Database()


