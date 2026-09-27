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

            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(created_at);
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_equity_created ON equity_snapshots(created_at);
            """)

    def record_trade(self, trade: TradeRecord) -> str:
        trade_id = trade.id or f"{trade.symbol}_{int(time.time()*1000)}"
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
                1 if trade.live else 0, trade.leverage, time.time()
            ))
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

    def get_equity_history(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT timestamp, balance, equity, unrealized_pnl, open_positions, created_at
            FROM equity_snapshots ORDER BY created_at ASC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_daily_metrics(self) -> Dict[str, Any]:
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            rows = conn.execute("""
            SELECT pnl, profit_protected FROM trades WHERE timestamp LIKE ?
            """, (f"{today_prefix}%",)).fetchall()
            
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
        """Clears all trades, equity snapshots, and signal history for a clean start."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM trades;")
            conn.execute("DELETE FROM equity_snapshots;")
            conn.execute("DELETE FROM signals_history;")

db = Database()


