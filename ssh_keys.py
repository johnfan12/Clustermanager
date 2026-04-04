"""SSH public key validation helpers."""

from __future__ import annotations

import base64
import hashlib
import re

SUPPORTED_SSH_KEY_TYPES = {
    "ssh-rsa",
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
}
MAX_SSH_KEYS_PER_USER = 10
MAX_SSH_PUBLIC_KEY_LENGTH = 8192
MAX_SSH_KEY_REMARK_LENGTH = 255
PRIVATE_KEY_MARKERS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
    "BEGIN PRIVATE KEY",
    "BEGIN DSA PRIVATE KEY",
)
SSH_KEY_PATTERN = re.compile(r"^\s*(?P<type>\S+)\s+(?P<body>\S+)(?:\s+(?P<comment>.*))?\s*$")


def _decode_public_key_blob(key_blob: str) -> bytes:
    padded = key_blob + ("=" * (-len(key_blob) % 4))
    return base64.b64decode(padded.encode("ascii"), validate=True)


def validate_ssh_public_key(public_key: str) -> str:
    """Validate and normalize an OpenSSH-format public key."""
    normalized = (public_key or "").strip()
    if not normalized:
        raise ValueError("SSH 公钥不能为空。")
    if len(normalized) > MAX_SSH_PUBLIC_KEY_LENGTH:
        raise ValueError("SSH 公钥过长。")
    if any(marker in normalized for marker in PRIVATE_KEY_MARKERS):
        raise ValueError("检测到私钥内容，请只粘贴公钥。")

    match = SSH_KEY_PATTERN.match(normalized)
    if not match:
        raise ValueError("SSH 公钥格式不正确。")

    key_type = match.group("type")
    key_blob = match.group("body")
    comment = (match.group("comment") or "").strip()

    if key_type not in SUPPORTED_SSH_KEY_TYPES:
        raise ValueError("仅支持 ssh-rsa、ssh-ed25519 和 ecdsa-sha2-* 公钥。")

    try:
        decoded = _decode_public_key_blob(key_blob)
    except Exception as exc:  # pragma: no cover - defensive, simple helper
        raise ValueError("SSH 公钥内容无法解析。") from exc

    if not decoded:
        raise ValueError("SSH 公钥内容为空。")

    return f"{key_type} {key_blob}" + (f" {comment}" if comment else "")


def compute_ssh_key_fingerprint(public_key: str) -> str:
    """Return OpenSSH-style SHA256 fingerprint for one public key."""
    normalized = validate_ssh_public_key(public_key)
    match = SSH_KEY_PATTERN.match(normalized)
    if match is None:
        raise ValueError("SSH 公钥格式不正确。")
    decoded = _decode_public_key_blob(match.group("body"))
    digest = hashlib.sha256(decoded).digest()
    fingerprint = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{fingerprint}"


def normalize_ssh_key_remark(remark: str | None) -> str:
    """Normalize optional SSH key remark."""
    normalized = (remark or "").strip()
    if len(normalized) > MAX_SSH_KEY_REMARK_LENGTH:
        raise ValueError(f"备注不能超过 {MAX_SSH_KEY_REMARK_LENGTH} 个字符。")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError("备注包含非法控制字符。")
    return normalized
