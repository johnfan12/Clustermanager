"""
认证模块 — JWT 生成 / 验证 / 登录端点
与各 gpu_manager 节点共享 JWT_SECRET，实现 SSO 免登录跳转。
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

import config

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ── Pydantic 模型 ──────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    """登录成功返回的 token 响应体。"""
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool


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


def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> str:
    """从 JWT token 中验证并提取用户名。

    Args:
        token: Bearer token（由 OAuth2PasswordBearer 自动提取）

    Returns:
        用户名字符串

    Raises:
        HTTPException: token 缺失或无效时返回 401
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或 token 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 token",
            )
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token 或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ── 登录端点 ───────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """管理员登录端点。

    目前仅支持 config 中配置的管理员账号，后续可对接各节点用户体系。

    Args:
        form: OAuth2 表单（username + password）

    Returns:
        包含 access_token 的响应体

    Raises:
        HTTPException: 用户名或密码错误时返回 401
    """
    if (
        form.username != config.ADMIN_USERNAME
        or form.password != config.ADMIN_PASSWORD
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    token = create_token(username=form.username, is_admin=True)
    return TokenResponse(
        access_token=token,
        username=form.username,
        is_admin=True,
    )
