"""Central GPU-hour billing for Clustermanager."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

import config
from database import SessionLocal
from models import ClusterGPUHourLedger, ClusterInstanceState, ClusterUser

LOGGER = logging.getLogger("cluster_manager.billing")

_billing_task: asyncio.Task[None] | None = None
_billing_lock = asyncio.Lock()


def ensure_cluster_user_record(
    db: Session, username: str, email: str | None = None
) -> ClusterUser:
    """Ensure a central user record exists before quota or billing operations."""
    user = db.get(ClusterUser, username)
    if user is not None:
        return user

    user = ClusterUser(
        username=username,
        email=email or f"{username}@local",
        password_hash="",
        gpu_hours_quota=config.GPU_HOURS_DEFAULT_QUOTA,
    )
    db.add(user)
    db.flush()
    return user


def gpu_hours_remaining(user: ClusterUser) -> float:
    quota = float(user.gpu_hours_quota or 0.0)
    used = float(user.gpu_hours_used or 0.0)
    frozen = float(user.gpu_hours_frozen or 0.0)
    return quota - used - frozen


def ensure_gpu_hours_available(
    db: Session, username: str, requested_gpu_count: int
) -> ClusterUser:
    """Reject GPU-bearing actions when the user has no remaining balance."""
    user = ensure_cluster_user_record(db, username)
    if requested_gpu_count <= 0:
        return user

    remaining = gpu_hours_remaining(user)
    if remaining <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Insufficient GPU-hour balance. "
                f"remaining={remaining:.4f}, required_gpu={requested_gpu_count}."
            ),
        )
    return user


def settle_instance_state(
    db: Session,
    state: ClusterInstanceState,
    settled_at: datetime,
    reason: str,
) -> float:
    """Accrue elapsed GPU hours for one centrally tracked instance."""
    if state.status != "running" or not state.node_online or state.last_billed_at is None:
        return 0.0

    elapsed_seconds = max(0.0, (settled_at - state.last_billed_at).total_seconds())
    increment = round((int(state.gpu_count) * elapsed_seconds) / 3600.0, 4)
    state.last_billed_at = settled_at

    if increment <= 0:
        return 0.0

    user = ensure_cluster_user_record(db, state.username)
    user.gpu_hours_used = float(user.gpu_hours_used or 0.0) + increment
    db.add(
        ClusterGPUHourLedger(
            username=state.username,
            node_id=state.node_id,
            node_instance_id=state.node_instance_id,
            container_name=state.container_name,
            delta_gpu_hours=increment,
            reason=reason,
            created_at=settled_at,
        )
    )
    return increment


def activate_instance_state(
    db: Session,
    *,
    node_id: str,
    node_instance_id: int,
    username: str,
    container_name: str,
    gpu_count: int,
    status: str,
    activated_at: datetime | None = None,
) -> ClusterInstanceState:
    """Mark an instance as active/running from a proxy action or sync snapshot."""
    now = activated_at or datetime.utcnow()
    state = (
        db.query(ClusterInstanceState)
        .filter(
            ClusterInstanceState.node_id == node_id,
            ClusterInstanceState.node_instance_id == node_instance_id,
        )
        .first()
    )
    if state is None:
        state = ClusterInstanceState(
            node_id=node_id,
            node_instance_id=node_instance_id,
            username=username,
            container_name=container_name,
        )
        db.add(state)

    state.username = username
    state.container_name = container_name
    state.gpu_count = max(0, int(gpu_count))
    state.status = status
    state.node_online = True
    state.last_seen_at = now
    state.last_billed_at = now if status == "running" else None
    return state


def settle_and_deactivate_instance(
    db: Session,
    *,
    node_id: str,
    node_instance_id: int,
    reason: str,
    status: str = "stopped",
    settled_at: datetime | None = None,
    delete_state: bool = False,
) -> None:
    """Settle a tracked instance and mark it inactive."""
    now = settled_at or datetime.utcnow()
    state = (
        db.query(ClusterInstanceState)
        .filter(
            ClusterInstanceState.node_id == node_id,
            ClusterInstanceState.node_instance_id == node_instance_id,
        )
        .first()
    )
    if state is None:
        return

    settle_instance_state(db, state, now, reason)
    if delete_state:
        db.delete(state)
        return

    state.status = status
    state.node_online = True
    state.last_seen_at = now
    state.last_billed_at = None


async def _fetch_node_admin_instances(
    client: httpx.AsyncClient, node_id: str, node_cfg: dict[str, Any]
) -> tuple[str, bool, list[dict[str, Any]]]:
    headers = {"Authorization": f"Bearer {node_cfg['admin_token']}"}
    try:
        response = await client.get(
            f"{node_cfg['api']}/api/admin/instances",
            headers=headers,
            timeout=config.PROXY_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        instances = payload if isinstance(payload, list) else payload.get("instances", [])
        if not isinstance(instances, list):
            instances = []
        return node_id, True, [inst for inst in instances if isinstance(inst, dict)]
    except Exception as exc:
        LOGGER.warning("Central billing sync failed for node %s: %s", node_id, exc)
        return node_id, False, []


def _mark_node_offline(db: Session, node_id: str) -> None:
    states = (
        db.query(ClusterInstanceState)
        .filter(ClusterInstanceState.node_id == node_id)
        .all()
    )
    for state in states:
        state.node_online = False
        state.last_billed_at = None


def _apply_online_snapshot(
    db: Session, node_id: str, instances: list[dict[str, Any]], observed_at: datetime
) -> None:
    current = {
        int(inst["id"]): inst
        for inst in instances
        if isinstance(inst.get("id"), int)
    }
    known_states = {
        state.node_instance_id: state
        for state in db.query(ClusterInstanceState)
        .filter(ClusterInstanceState.node_id == node_id)
        .all()
    }

    for node_instance_id, state in list(known_states.items()):
        snapshot = current.pop(node_instance_id, None)
        if snapshot is None:
            if state.status == "running" and state.node_online:
                settle_instance_state(db, state, observed_at, reason="sync_disappeared")
            db.delete(state)
            continue
        _sync_state_with_snapshot(db, state, snapshot, observed_at)

    for snapshot in current.values():
        username = str(snapshot.get("username") or "")
        if not username:
            continue
        ensure_cluster_user_record(db, username)
        activate_instance_state(
            db,
            node_id=node_id,
            node_instance_id=int(snapshot["id"]),
            username=username,
            container_name=str(snapshot.get("container_name") or ""),
            gpu_count=len(list(snapshot.get("gpu_indices") or [])),
            status=str(snapshot.get("status") or "unknown"),
            activated_at=observed_at,
        )


def _sync_state_with_snapshot(
    db: Session,
    state: ClusterInstanceState,
    snapshot: dict[str, Any],
    observed_at: datetime,
) -> None:
    previous_status = state.status
    previous_online = state.node_online
    next_status = str(snapshot.get("status") or "unknown")
    next_gpu_count = len(list(snapshot.get("gpu_indices") or []))
    username = str(snapshot.get("username") or state.username)

    ensure_cluster_user_record(db, username)

    if previous_status == "running" and previous_online:
        if next_status != "running" or next_gpu_count != state.gpu_count:
            settle_instance_state(db, state, observed_at, reason="sync_transition")
        elif next_status == "running":
            settle_instance_state(db, state, observed_at, reason="sync_tick")

    state.username = username
    state.container_name = str(snapshot.get("container_name") or state.container_name)
    state.gpu_count = next_gpu_count
    state.status = next_status
    state.node_online = True
    state.last_seen_at = observed_at

    if next_status == "running":
        if previous_status != "running" or not previous_online:
            state.last_billed_at = observed_at
    else:
        state.last_billed_at = None


async def sync_billing_once() -> None:
    """Synchronize central billing state from all currently reachable nodes."""
    if _billing_lock.locked():
        return

    async with _billing_lock:
        observed_at = datetime.utcnow()
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *[
                    _fetch_node_admin_instances(client, node_id, node_cfg)
                    for node_id, node_cfg in config.NODES.items()
                ]
            )

        with SessionLocal() as db:
            try:
                for node_id, online, instances in results:
                    if online:
                        _apply_online_snapshot(db, node_id, instances, observed_at)
                    else:
                        _mark_node_offline(db, node_id)
                db.commit()
            except Exception:
                db.rollback()
                LOGGER.exception("Central billing sync failed")


async def _billing_loop() -> None:
    while True:
        await sync_billing_once()
        await asyncio.sleep(config.GPU_HOURS_SYNC_INTERVAL_SECONDS)


async def start_billing_sync() -> None:
    """Start the background sync task once."""
    global _billing_task
    if _billing_task is None or _billing_task.done():
        _billing_task = asyncio.create_task(_billing_loop())


async def stop_billing_sync() -> None:
    """Stop the background sync task if it is running."""
    global _billing_task
    if _billing_task is None:
        return
    _billing_task.cancel()
    try:
        await _billing_task
    except asyncio.CancelledError:
        pass
    _billing_task = None
