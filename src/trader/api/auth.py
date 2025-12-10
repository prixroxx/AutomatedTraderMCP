"""
Authentication manager for Groww API.

This module handles authentication token management,
including token generation, refresh, and caching.
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from growwapi import GrowwAPI

from .exceptions import AuthenticationError
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class AuthManager:
    """
    Manages authentication with Groww API.

    Responsibilities:
    - Generate access tokens
    - Cache tokens to avoid frequent regeneration
    - Handle token refresh
    - Validate credentials
    """

    def __init__(self, api_key: Optional[str] = None, secret: Optional[str] = None):
        """
        Initialize authentication manager.

        Args:
            api_key: Groww API key (from environment if not provided)
            secret: Groww API secret (from environment if not provided)
        """
        self.api_key = api_key or os.getenv('GROWW_API_KEY')
        self.secret = secret or os.getenv('GROWW_SECRET')

        if not self.api_key or not self.secret:
            raise AuthenticationError(
                "Groww API credentials not found. "
                "Set GROWW_API_KEY and GROWW_SECRET in environment or pass to constructor."
            )

        self._access_token: Optional[str] = None
        self._token_created_at: Optional[datetime] = None
        self._token_ttl: int = 24 * 3600  # 24 hours (Groww tokens typically valid for 1 day)

        logger.info("Authentication manager initialized")

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """
        Get valid access token, generating new one if needed.

        Args:
            force_refresh: Force token refresh even if current token is valid

        Returns:
            Valid access token

        Raises:
            AuthenticationError: If authentication fails
        """
        # Check if we have a valid cached token
        if not force_refresh and self._is_token_valid():
            logger.debug("Using cached access token")
            return self._access_token

        # Generate new token
        try:
            logger.info("Generating new access token")

            # Use Groww API to get access token
            access_token = GrowwAPI.get_access_token(
                api_key=self.api_key,
                secret=self.secret
            )

            if not access_token:
                raise AuthenticationError("Failed to get access token - empty response")

            # Cache the token
            self._access_token = access_token
            self._token_created_at = datetime.now()

            logger.info("Access token generated successfully")

            return self._access_token

        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise AuthenticationError(f"Failed to authenticate with Groww: {str(e)}")

    def _is_token_valid(self) -> bool:
        """
        Check if cached token is still valid.

        Returns:
            True if token exists and hasn't expired
        """
        if not self._access_token or not self._token_created_at:
            return False

        # Check if token has expired (with 1-hour safety margin)
        token_age = (datetime.now() - self._token_created_at).total_seconds()
        safety_margin = 3600  # 1 hour

        is_valid = token_age < (self._token_ttl - safety_margin)

        if not is_valid:
            logger.debug(
                "Token expired",
                age_seconds=token_age,
                ttl_seconds=self._token_ttl
            )

        return is_valid

    def invalidate_token(self) -> None:
        """
        Invalidate cached token, forcing refresh on next request.
        """
        logger.info("Invalidating cached access token")
        self._access_token = None
        self._token_created_at = None

    def get_token_info(self) -> dict:
        """
        Get information about current token.

        Returns:
            Dictionary with token status information
        """
        if not self._access_token:
            return {
                'has_token': False,
                'is_valid': False
            }

        token_age = (datetime.now() - self._token_created_at).total_seconds() if self._token_created_at else None
        time_remaining = (self._token_ttl - token_age) if token_age else None

        return {
            'has_token': True,
            'is_valid': self._is_token_valid(),
            'created_at': self._token_created_at.isoformat() if self._token_created_at else None,
            'age_seconds': token_age,
            'time_remaining_seconds': time_remaining,
            'ttl_seconds': self._token_ttl
        }
