"""Google OAuth + JWT authentication for the dashboard.

Same pattern as Golf Trip Planner: Google Sign-In → verify token → issue JWT.
Single allowed user: ALLOWED_EMAIL env var (default: your-email@example.com).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Auto-load .env from repo root (same as golf project's Docker env_file)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # dotenv not installed — env vars must be set externally

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7


def _get_google_client_id():
    return os.getenv("GOOGLE_CLIENT_ID", "")


def _get_jwt_secret():
    return os.getenv("JWT_SECRET_KEY", "hth-dashboard-change-me")


def _get_allowed_email():
    return os.getenv("ALLOWED_EMAIL", "your-email@example.com")


def verify_google_token(token: str) -> Optional[dict]:
    """Verify a Google ID token. Returns user info or None."""
    client_id = _get_google_client_id()
    if not client_id:
        return None
    try:
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), client_id
        )
        if idinfo["iss"] not in ("accounts.google.com", "https://accounts.google.com"):
            return None
        return {
            "email": idinfo["email"],
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
        }
    except Exception as e:
        print(f"[Auth] Google token verification failed: {e}")
        return None


def is_allowed(email: str) -> bool:
    """Check if email is in the allowed list."""
    return email.lower() == _get_allowed_email().lower()


def create_jwt(email: str, name: str = "") -> str:
    """Create a JWT for an authenticated user."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": email, "name": name, "iat": now, "exp": now + timedelta(days=JWT_EXPIRY_DAYS)},
        _get_jwt_secret(),
        algorithm=JWT_ALGORITHM,
    )


def verify_jwt(token: str) -> Optional[dict]:
    """Verify a JWT. Returns payload or None."""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
