"""认证模块 - JWT 验证、节点登录代理与注册代理。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

import config
from user_store import (
    get_cluster_user,
    init_user_store,
    upsert_cluster_user,
    verify_cluster_user_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
AUTH_REQUEST_TIMEOUT = 8.0


# ── Pydantic 模型 ──────────────────────────────────────────────────────────


class TokenResponse(BaseModel):
    """登录成功返回的 token 响应体。"""

    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool
    user: dict[str, Any] | None = None
    node_id: str | None = None
    node_name: str | None = None
    entry_url: str | None = None
    message: str | None = None


class NodeLoginRequest(BaseModel):
    """用户登录到指定节点。"""

    node_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class NodeRegisterRequest(BaseModel):
    """用户在指定节点注册账号。"""

    node_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    email: str
    password: str = Field(min_length=6, max_length=128)


# ── JWT 工具函数 ───────────────────────────────────────────────────────────


def create_token(username: str, is_admin: bool = False) -> str:
    """生成 JWT token。

    Args:
        username: 用户名
        is_admin: 是否管理员

    Returns:
        编码后的 JWT 字符串
    """
    expire = datetime.utcnow() + timedelta(hours=config.JWT_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def _get_node_config(node_id: str) -> dict[str, Any]:
    """返回指定节点配置，不存在时抛出 404。"""
    node_cfg = config.NODES.get(node_id)
    if node_cfg is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    return node_cfg


def _build_entry_url(node_id: str, token: str) -> str | None:
    """构造进入节点 Web 管理页的免登录地址。"""
    base_url = config.NODE_WEB_URLS.get(node_id)
    if not base_url:
        return None
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={token}"


def _extract_error_detail(response: httpx.Response) -> str:
    """从节点响应中提取可读错误信息。"""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message")
        if isinstance(detail, str) and detail:
            return detail
    text = response.text.strip()
    return text or "请求失败"


async def _request_node_json(
    node_id: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """向指定节点发送 JSON 请求并返回响应。"""
    node_cfg = _get_node_config(node_id)
    url = f"{node_cfg['api']}{path}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                json=payload,
                timeout=AUTH_REQUEST_TIMEOUT,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503, detail=f"节点 {node_cfg['name']} 暂时不可用"
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_extract_error_detail(response),
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="节点返回了无效响应") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="节点返回格式不正确")
    return data


def _build_token_response(
    node_id: str,
    access_token: str,
    user_payload: dict[str, Any] | None,
    message: str | None = None,
) -> TokenResponse:
    """统一组装登录/注册成功响应。"""
    node_cfg = _get_node_config(node_id)
    user_info = user_payload or {}
    username = str(user_info.get("username") or "")
    is_admin = bool(user_info.get("is_admin", False))
    return TokenResponse(
        access_token=access_token,
        username=username,
        is_admin=is_admin,
        user=user_payload,
        node_id=node_id,
        node_name=str(node_cfg.get("name") or node_id),
        entry_url=_build_entry_url(node_id, access_token),
        message=message,
    )


def _build_cluster_local_login_response(
    username: str,
    is_admin: bool = False,
    message: str | None = None,
) -> TokenResponse:
    """Build a local Clustermanager login response when node is unavailable."""
    token = create_token(username=username, is_admin=is_admin)
    user_payload = {
        "username": username,
        "is_admin": is_admin,
    }
    return TokenResponse(
        access_token=token,
        username=username,
        is_admin=is_admin,
        user=user_payload,
        message=message,
    )


async def _login_to_node(node_id: str, username: str, password: str) -> TokenResponse:
    """向节点执行登录并返回聚合后的响应。"""
    data = await _request_node_json(
        node_id,
        "POST",
        "/api/auth/login",
        {"username": username, "password": password},
    )
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(status_code=502, detail="节点未返回 access_token")
    user_payload = data.get("user")
    if user_payload is not None and not isinstance(user_payload, dict):
        user_payload = None
    return _build_token_response(node_id, access_token, user_payload)


async def _register_to_node(
    node_id: str,
    username: str,
    email: str,
    password: str,
) -> None:
    """Register an account on the target node."""
    await _request_node_json(
        node_id,
        "POST",
        "/api/auth/register",
        {
            "username": username,
            "email": email,
            "password": password,
        },
    )


async def _fetch_node_auth_meta(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: dict[str, Any],
) -> dict[str, Any]:
    """查询节点注册能力与在线状态，供前端认证页展示。"""
    result = {
        "node_id": node_id,
        "name": node_cfg.get("name", node_id),
        "web_url": config.NODE_WEB_URLS.get(node_id, ""),
        "online": False,
        "allow_register": False,
    }
    try:
        response = await client.get(
            f"{node_cfg['api']}/api/meta",
            timeout=3.0,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            result["allow_register"] = bool(payload.get("allow_register", False))
        result["online"] = True
    except Exception:
        pass
    return result


def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """从 JWT token 中验证并提取用户名。

    Args:
        token: Bearer token（由 OAuth2PasswordBearer 自动提取）

    Returns:
        用户名字符串

    Raises:
        HTTPException: token 缺失或无效时返回 401
    """
    user_info = get_current_user_info(token)
    return str(user_info["username"])


def get_current_user_info(
    token: Optional[str] = Depends(oauth2_scheme),
) -> dict[str, Any]:
    """从 JWT token 中验证并提取用户信息。"""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或 token 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token 或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username: Optional[str] = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
        )
    return {
        "username": username,
        "is_admin": bool(payload.get("is_admin", False)),
    }


def get_optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    """尝试从 token 中提取用户名，失败时返回 None（不抛异常）。

    Args:
        token: Bearer token

    Returns:
        用户名字符串或 None
    """
    if token is None:
        return None
    try:
        payload = jwt.decode(
            token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM]
        )
        return payload.get("sub")
    except JWTError:
        return None


# ── 登录端点 ───────────────────────────────────────────────────────────────


@router.get("/nodes")
async def list_auth_nodes() -> dict[str, list[dict[str, Any]]]:
    """返回可登录/注册的节点列表。"""
    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_node_auth_meta(client, node_id, node_cfg)
            for node_id, node_cfg in config.NODES.items()
        ]
        nodes = await asyncio.gather(*tasks)
    return {"nodes": nodes}


@router.post("/login", response_model=TokenResponse)
async def login(payload: NodeLoginRequest) -> TokenResponse:
    """将登录请求转发到用户选择的 Servermanager 节点。"""
    try:
        return await _login_to_node(payload.node_id, payload.username, payload.password)
    except HTTPException as exc:
        # Node unavailable: allow local login with central user store credentials.
        if exc.status_code in (502, 503):
            if (
                payload.username == config.ADMIN_USERNAME
                and payload.password == config.ADMIN_PASSWORD
            ):
                return _build_cluster_local_login_response(
                    username=payload.username,
                    is_admin=True,
                    message="节点离线，已登录聚合层管理员账号",
                )

            if verify_cluster_user_password(payload.username, payload.password):
                return _build_cluster_local_login_response(
                    username=payload.username,
                    is_admin=False,
                    message="节点离线，已登录聚合层账号；节点恢复后可继续进入服务器",
                )

            raise HTTPException(status_code=401, detail="用户名或密码错误") from exc

        should_try_provision = (
            config.AUTO_PROVISION_ON_NODE_LOGIN and exc.status_code in (401, 404)
        )
        if not should_try_provision:
            raise

        central_user = get_cluster_user(payload.username)
        if central_user is None:
            raise

        if not verify_cluster_user_password(payload.username, payload.password):
            raise HTTPException(status_code=401, detail="用户名或密码错误") from exc

        try:
            await _register_to_node(
                payload.node_id,
                payload.username,
                central_user["email"],
                payload.password,
            )
        except HTTPException as reg_exc:
            if reg_exc.status_code not in (400, 409):
                raise

        token_response = await _login_to_node(
            payload.node_id,
            payload.username,
            payload.password,
        )
        token_response.message = "已自动将账号同步到该节点"
        return token_response


@router.post("/register", response_model=TokenResponse)
async def register(payload: NodeRegisterRequest) -> TokenResponse:
    """注册聚合层账号；节点在线则同步到节点并自动登录。"""
    upsert_cluster_user(payload.username, payload.email, payload.password)

    try:
        await _register_to_node(
            payload.node_id,
            payload.username,
            payload.email,
            payload.password,
        )
        token_response = await _login_to_node(
            payload.node_id,
            payload.username,
            payload.password,
        )
        token_response.message = "注册成功，已自动登录"
        return token_response
    except HTTPException as exc:
        # 节点离线或当前节点未开放注册：先完成聚合层注册与登录。
        if exc.status_code in (400, 403, 409, 502, 503):
            token_response = _build_cluster_local_login_response(
                username=payload.username,
                is_admin=False,
                message="已完成聚合层注册；节点恢复或切换后会自动同步账号",
            )
            return token_response
        raise


@router.get("/me")
async def me(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """返回当前聚合层登录用户名。"""
    return {"username": username}


@router.on_event("startup")
async def _auth_startup() -> None:
    """Initialize central user store for node auto-provision."""
    init_user_store()
