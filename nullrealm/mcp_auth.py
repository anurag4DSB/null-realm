"""Google OAuth token exchange and MCP JWT management.

Handles the OAuth2 authorization code flow with Google and issues
short-lived JWTs for MCP clients.
"""

import logging
import os
from datetime import UTC, datetime, timedelta

import httpx
import jwt

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
MCP_JWT_SECRET = os.getenv("MCP_JWT_SECRET", "dev-secret-change-me")
REDIRECT_URI = os.getenv(
    "MCP_REDIRECT_URI",
    "http://hopocalypse.34.53.165.155.nip.io/oauth/callback",
)


async def get_authorize_url(state: str = "") -> str:
    """Build Google OAuth2 authorization URL."""
    return (
        "https://accounts.google.com/o/oauth2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        "&scope=email+profile"
        "&access_type=offline"
        "&prompt=select_account"
        f"&state={state}"
    )


async def exchange_code(code: str) -> dict:
    """Exchange an authorization code for Google tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_user_email(access_token: str) -> str:
    """Fetch the authenticated user's email from Google."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()["email"]


def create_mcp_token(email: str) -> str:
    """Issue a 24-hour MCP JWT for *email*."""
    return jwt.encode(
        {
            "email": email,
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iss": "null-realm-mcp",
        },
        MCP_JWT_SECRET,
        algorithm="HS256",
    )


def verify_mcp_token(token: str) -> dict:
    """Verify and decode an MCP JWT. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(token, MCP_JWT_SECRET, algorithms=["HS256"])
