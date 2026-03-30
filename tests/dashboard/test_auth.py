"""Tests for dashboard Google OAuth + JWT authentication."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

from dashboard.api.auth import (
    is_allowed, create_jwt, verify_jwt, verify_google_token,
)


class TestIsAllowed:

    def test_allowed_email(self):
        assert is_allowed("test@example.com") is True

    def test_allowed_case_insensitive(self):
        assert is_allowed("Hjalti@Gmail.com") is True

    def test_disallowed_email(self):
        assert is_allowed("random@gmail.com") is False

    def test_empty_email(self):
        assert is_allowed("") is False

    def test_custom_allowed_email(self):
        with patch.dict(os.environ, {"ALLOWED_EMAIL": "other@test.com"}):
            # Re-import to pick up env change
            from importlib import reload
            import dashboard.api.auth as auth_mod
            reload(auth_mod)
            assert auth_mod.is_allowed("other@test.com") is True
            assert auth_mod.is_allowed("test@example.com") is False
            # Restore
            reload(auth_mod)


class TestJWT:

    def test_create_and_verify(self):
        token = create_jwt("test@example.com", "Hjalti")
        payload = verify_jwt(token)
        assert payload is not None
        assert payload["sub"] == "test@example.com"
        assert payload["name"] == "Hjalti"

    def test_invalid_token(self):
        assert verify_jwt("garbage.token.here") is None

    def test_empty_token(self):
        assert verify_jwt("") is None

    def test_tampered_token(self):
        token = create_jwt("test@example.com")
        # Flip a character
        tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
        assert verify_jwt(tampered) is None


class TestVerifyGoogleToken:

    def test_no_client_id(self):
        """Returns None when GOOGLE_CLIENT_ID is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GOOGLE_CLIENT_ID", None)
            from importlib import reload
            import dashboard.api.auth as auth_mod
            reload(auth_mod)
            assert auth_mod.verify_google_token("some-token") is None
            reload(auth_mod)

    def test_invalid_token(self):
        """Returns None for an invalid token."""
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "test-client-id"}):
            from importlib import reload
            import dashboard.api.auth as auth_mod
            reload(auth_mod)
            result = auth_mod.verify_google_token("invalid-token")
            assert result is None
            reload(auth_mod)
