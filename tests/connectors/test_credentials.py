# tests/connectors/test_credentials.py
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest

from app.connectors.base import CredentialsExpiredError
from app.connectors.credentials import CredentialManager


def _mock_db_with_scalar(value):
    """Return an AsyncMock db where execute().scalar_one_or_none() returns value."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    mock_db.execute.return_value = mock_result
    return mock_db


async def test_get_raises_when_no_integration():
    """CredentialManager.get raises CredentialsExpiredError if no DB row exists."""
    manager = CredentialManager()
    mock_db = _mock_db_with_scalar(None)

    with pytest.raises(CredentialsExpiredError):
        await manager.get("user_1", "gmail", mock_db)


async def test_get_raises_when_inactive():
    """CredentialManager.get raises CredentialsExpiredError if active=False."""
    manager = CredentialManager()
    mock_integration = MagicMock()
    mock_integration.active = False

    mock_db = _mock_db_with_scalar(mock_integration)

    with pytest.raises(CredentialsExpiredError):
        await manager.get("user_1", "gmail", mock_db)


async def test_get_returns_decrypted_creds_no_refresh():
    """CredentialManager.get returns decrypted creds dict for a non-Google connector."""
    manager = CredentialManager()

    mock_integration = MagicMock()
    mock_integration.active = True

    # encrypt_credentials / decrypt_credentials need a real key in settings
    # — patch decrypt_credentials directly
    expected_creds = {"access_token": "tok_abc"}
    mock_db = _mock_db_with_scalar(mock_integration)

    with patch("app.connectors.credentials.decrypt_credentials", return_value=expected_creds):
        result = await manager.get("user_1", "notion", mock_db)

    assert result == expected_creds


async def test_deactivate_sets_active_false():
    """CredentialManager.deactivate sets active=False and commits."""
    manager = CredentialManager()
    mock_integration = MagicMock()
    mock_integration.active = True

    mock_db = _mock_db_with_scalar(mock_integration)

    await manager.deactivate("user_1", "gmail", mock_db)

    assert mock_integration.active is False
    mock_db.commit.assert_called_once()
