"""Persistent node health tracking for the simplified console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
RUNTIME_DIR = BASE_DIR / os.environ.get("SIMPLE_RUNTIME_DIR", "runtime")
DATABASE_PATH = Path(
    os.environ.get("SIMPLE_NODE_STATUS_DB", str(RUNTIME_DIR / "simple-cluster-node-status.db"))
)


@dataclass(frozen=True)
class NodeHealth:
    node_id: str
    name: str
    online: bool
    uptime_seconds: int | None
    issue: str
    issue_seconds: int | None
    last_seen_at: str | None
    last_ok_at: str | None
    ssh_checked: bool
    ssh_online: bool
    ssh_uptime_seconds: int | None
    ssh_issue: str
    ssh_issue_seconds: int | None
    ssh_last_ok_at: str | None
    ssh_host: str
    ssh_port: int | None


def _ensure_node_health_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(node_health)").fetchall()
    }
    required_columns = {
        "ssh_checked": "ssh_checked INTEGER NOT NULL DEFAULT 0",
        "ssh_online": "ssh_online INTEGER NOT NULL DEFAULT 0",
        "ssh_online_since": "ssh_online_since TEXT",
        "ssh_last_ok_at": "ssh_last_ok_at TEXT",
        "ssh_issue": "ssh_issue TEXT NOT NULL DEFAULT ''",
        "ssh_issue_since": "ssh_issue_since TEXT",
        "ssh_host": "ssh_host TEXT",
        "ssh_port": "ssh_port INTEGER",
    }
    for column_name, ddl in required_columns.items():
        if column_name not in existing_columns:
            connection.execute(f"ALTER TABLE node_health ADD COLUMN {ddl}")


def init_node_status_store() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS node_health (
                node_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                online INTEGER NOT NULL DEFAULT 0,
                online_since TEXT,
                last_seen_at TEXT,
                last_ok_at TEXT,
                issue TEXT NOT NULL DEFAULT '',
                issue_since TEXT,
                ssh_checked INTEGER NOT NULL DEFAULT 0,
                ssh_online INTEGER NOT NULL DEFAULT 0,
                ssh_online_since TEXT,
                ssh_last_ok_at TEXT,
                ssh_issue TEXT NOT NULL DEFAULT '',
                ssh_issue_since TEXT,
                ssh_host TEXT,
                ssh_port INTEGER,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_node_health_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_node_status (
                node_id TEXT NOT NULL,
                date TEXT NOT NULL,
                online INTEGER NOT NULL DEFAULT 0,
                checks_total INTEGER NOT NULL DEFAULT 0,
                checks_ok INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (node_id, date)
            )
            """
        )
        connection.commit()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _elapsed_seconds(started_at: str | None, now: datetime) -> int | None:
    parsed = _parse_iso(started_at)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def update_node_health(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    init_node_status_store()
    now = _utc_now()
    now_text = _iso(now)
    today_text = now.strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        for node in nodes:
            node_id = str(node.get("node_id") or node.get("id") or "")
            if not node_id:
                continue
            name = str(node.get("name") or node_id)
            online = bool(node.get("online"))
            issue = "" if online else str(node.get("error") or "Node is offline.")
            ssh = node.get("ssh") if isinstance(node.get("ssh"), dict) else {}
            ssh_checked = bool(ssh.get("checked"))
            ssh_online = bool(ssh.get("online")) if ssh_checked else False
            ssh_host = str(ssh.get("host") or node.get("ssh_host") or "")
            raw_ssh_port = ssh.get("port") if ssh.get("port") is not None else node.get("ssh_port")
            try:
                ssh_port = int(raw_ssh_port) if raw_ssh_port not in (None, "") else None
            except (TypeError, ValueError):
                ssh_port = None
            ssh_issue = (
                ""
                if ssh_online
                else str(ssh.get("error") or ("SSH is offline." if ssh_checked else "SSH check is not configured."))
            )

            existing = connection.execute(
                "SELECT * FROM node_health WHERE node_id = ?",
                (node_id,),
            ).fetchone()

            if online:
                online_since = (
                    str(existing["online_since"])
                    if existing is not None and bool(existing["online"]) and existing["online_since"]
                    else now_text
                )
                issue_since = None
                last_ok_at = now_text
                issue_text = ""
            else:
                previous_issue = str(existing["issue"] or "") if existing is not None else ""
                issue_since = (
                    str(existing["issue_since"])
                    if existing is not None
                    and not bool(existing["online"])
                    and existing["issue_since"]
                    and previous_issue == issue
                    else now_text
                )
                online_since = None
                last_ok_at = str(existing["last_ok_at"]) if existing is not None and existing["last_ok_at"] else None
                issue_text = issue

            if ssh_checked and ssh_online:
                ssh_online_since = (
                    str(existing["ssh_online_since"])
                    if existing is not None
                    and bool(existing["ssh_checked"])
                    and bool(existing["ssh_online"])
                    and existing["ssh_online_since"]
                    else now_text
                )
                ssh_issue_since = None
                ssh_last_ok_at = now_text
                ssh_issue_text = ""
            elif ssh_checked:
                previous_ssh_issue = str(existing["ssh_issue"] or "") if existing is not None else ""
                ssh_issue_since = (
                    str(existing["ssh_issue_since"])
                    if existing is not None
                    and bool(existing["ssh_checked"])
                    and not bool(existing["ssh_online"])
                    and existing["ssh_issue_since"]
                    and previous_ssh_issue == ssh_issue
                    else now_text
                )
                ssh_online_since = None
                ssh_last_ok_at = (
                    str(existing["ssh_last_ok_at"])
                    if existing is not None and existing["ssh_last_ok_at"]
                    else None
                )
                ssh_issue_text = ssh_issue
            else:
                ssh_online_since = None
                ssh_issue_since = None
                ssh_last_ok_at = (
                    str(existing["ssh_last_ok_at"])
                    if existing is not None and existing["ssh_last_ok_at"]
                    else None
                )
                ssh_issue_text = ssh_issue

            connection.execute(
                """
                INSERT INTO node_health (
                    node_id, name, online, online_since, last_seen_at,
                    last_ok_at, issue, issue_since, ssh_checked, ssh_online,
                    ssh_online_since, ssh_last_ok_at, ssh_issue, ssh_issue_since,
                    ssh_host, ssh_port, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    name = excluded.name,
                    online = excluded.online,
                    online_since = excluded.online_since,
                    last_seen_at = excluded.last_seen_at,
                    last_ok_at = excluded.last_ok_at,
                    issue = excluded.issue,
                    issue_since = excluded.issue_since,
                    ssh_checked = excluded.ssh_checked,
                    ssh_online = excluded.ssh_online,
                    ssh_online_since = excluded.ssh_online_since,
                    ssh_last_ok_at = excluded.ssh_last_ok_at,
                    ssh_issue = excluded.ssh_issue,
                    ssh_issue_since = excluded.ssh_issue_since,
                    ssh_host = excluded.ssh_host,
                    ssh_port = excluded.ssh_port,
                    updated_at = excluded.updated_at
                """,
                (
                    node_id,
                    name,
                    1 if online else 0,
                    online_since,
                    now_text,
                    last_ok_at,
                    issue_text,
                    issue_since,
                    1 if ssh_checked else 0,
                    1 if ssh_online else 0,
                    ssh_online_since,
                    ssh_last_ok_at,
                    ssh_issue_text,
                    ssh_issue_since,
                    ssh_host,
                    ssh_port,
                    now_text,
                ),
            )

            # Record daily status snapshot
            connection.execute(
                """
                INSERT INTO daily_node_status (node_id, date, online, checks_total, checks_ok)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(node_id, date) DO UPDATE SET
                    online = CASE WHEN excluded.online = 1 THEN 1 ELSE daily_node_status.online END,
                    checks_total = daily_node_status.checks_total + 1,
                    checks_ok = daily_node_status.checks_ok + excluded.checks_ok
                """,
                (node_id, today_text, 1 if online else 0, 1 if online else 0),
            )
        connection.commit()

    configured = [
        {"node_id": str(node.get("node_id") or node.get("id") or ""), "name": str(node.get("name") or "")}
        for node in nodes
    ]
    rows = list_node_health(configured)
    return rows


def list_node_health(configured_nodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    init_node_status_store()
    now = _utc_now()
    configured_nodes = configured_nodes or []
    configured_by_id = {
        str(node.get("node_id") or node.get("id") or ""): node
        for node in configured_nodes
        if str(node.get("node_id") or node.get("id") or "")
    }

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        stored_rows = {
            str(row["node_id"]): row
            for row in connection.execute("SELECT * FROM node_health ORDER BY name, node_id")
        }

    node_ids = list(configured_by_id.keys())
    for node_id in stored_rows:
        if node_id not in configured_by_id:
            node_ids.append(node_id)

    result: list[dict[str, Any]] = []
    for node_id in node_ids:
        row = stored_rows.get(node_id)
        configured = configured_by_id.get(node_id, {})
        configured_name = str(configured.get("name") or "")
        configured_ssh_host = str(configured.get("ssh_host") or "")
        raw_configured_ssh_port = configured.get("ssh_port")
        try:
            configured_ssh_port = (
                int(raw_configured_ssh_port)
                if raw_configured_ssh_port not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            configured_ssh_port = None
        if row is None:
            result.append(
                {
                    "node_id": node_id,
                    "name": configured_name or node_id,
                    "online": False,
                    "uptime_seconds": None,
                    "issue": "尚未检查",
                    "issue_seconds": None,
                    "last_seen_at": None,
                    "last_ok_at": None,
                    "ssh_checked": False,
                    "ssh_online": False,
                    "ssh_uptime_seconds": None,
                    "ssh_issue": "尚未检查",
                    "ssh_issue_seconds": None,
                    "ssh_last_ok_at": None,
                    "ssh_host": configured_ssh_host,
                    "ssh_port": configured_ssh_port,
                }
            )
            continue

        online = bool(row["online"])
        ssh_checked = bool(row["ssh_checked"])
        ssh_online = bool(row["ssh_online"]) if ssh_checked else False
        ssh_issue = str(row["ssh_issue"] or "")
        if not ssh_issue:
            ssh_issue = "SSH is offline." if ssh_checked else "尚未检查"
        result.append(
            {
                "node_id": node_id,
                "name": str(row["name"] or configured_name or node_id),
                "online": online,
                "uptime_seconds": _elapsed_seconds(row["online_since"], now) if online else None,
                "issue": "" if online else str(row["issue"] or "Node is offline."),
                "issue_seconds": None if online else _elapsed_seconds(row["issue_since"], now),
                "last_seen_at": row["last_seen_at"],
                "last_ok_at": row["last_ok_at"],
                "ssh_checked": ssh_checked,
                "ssh_online": ssh_online,
                "ssh_uptime_seconds": (
                    _elapsed_seconds(row["ssh_online_since"], now)
                    if ssh_checked and ssh_online
                    else None
                ),
                "ssh_issue": "" if ssh_checked and ssh_online else ssh_issue,
                "ssh_issue_seconds": (
                    _elapsed_seconds(row["ssh_issue_since"], now)
                    if ssh_checked and not ssh_online
                    else None
                ),
                "ssh_last_ok_at": row["ssh_last_ok_at"],
                "ssh_host": str(row["ssh_host"] or configured_ssh_host),
                "ssh_port": row["ssh_port"] if row["ssh_port"] is not None else configured_ssh_port,
            }
        )
    return result


def list_node_health_history(
    configured_nodes: list[dict[str, str]] | None = None,
    days: int = 30,
) -> dict[str, list[dict[str, Any]]]:
    """Return per-node daily status for the last `days` days.

    Returns a dict keyed by node_id, each value is a list of
    {date, online, checks_total, checks_ok} dicts sorted ascending by date.
    Days with no data get online=False, checks_total=0, checks_ok=0.
    """
    from datetime import timedelta

    init_node_status_store()
    now = _utc_now()
    configured_nodes = configured_nodes or []
    node_ids = [
        str(node.get("node_id") or node.get("id") or "")
        for node in configured_nodes
        if str(node.get("node_id") or node.get("id") or "")
    ]

    # Build date range
    date_range: list[str] = []
    for i in range(days - 1, -1, -1):
        d = now - timedelta(days=i)
        date_range.append(d.strftime("%Y-%m-%d"))

    start_date = date_range[0]
    result: dict[str, list[dict[str, Any]]] = {}

    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        # Fetch all daily records in the window
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            rows = connection.execute(
                f"SELECT * FROM daily_node_status WHERE node_id IN ({placeholders}) AND date >= ? ORDER BY date",
                (*node_ids, start_date),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM daily_node_status WHERE date >= ? ORDER BY date",
                (start_date,),
            ).fetchall()

    # Index by (node_id, date)
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        nid = str(row["node_id"])
        by_key[(nid, str(row["date"]))] = {
            "date": str(row["date"]),
            "online": bool(row["online"]),
            "checks_total": int(row["checks_total"]),
            "checks_ok": int(row["checks_ok"]),
        }
        if nid not in node_ids:
            node_ids.append(nid)

    for nid in node_ids:
        entries: list[dict[str, Any]] = []
        for d in date_range:
            if (nid, d) in by_key:
                entries.append(by_key[(nid, d)])
            else:
                entries.append({
                    "date": d,
                    "online": False,
                    "checks_total": 0,
                    "checks_ok": 0,
                })
        result[nid] = entries

    return result
