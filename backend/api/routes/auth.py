"""
Authentication Routes.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from backend.api.dependencies import AppStateDep
from backend.api.schemas import AuthStatus, LoginUrlResponse, SuccessResponse
from backend.broker.paper import PaperBroker
from backend.broker.session import load_access_token, load_session
from backend.config import settings
from backend.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/status", response_model=AuthStatus)
async def get_auth_status(state: AppStateDep):
    """
    Get current authentication status.
    """
    # Check for existing session
    session = load_session()

    if session and state.is_authenticated:
        return AuthStatus(
            authenticated=True,
            user_id=session.get("user_id"),
            user_name=session.get("user_name"),
            session_valid=True,
            expires_at=session.get("expires_at"),
        )

    if session:
        return AuthStatus(
            authenticated=False,
            user_id=session.get("user_id"),
            user_name=session.get("user_name"),
            session_valid=False,
            expires_at="Session expired - re-authenticate required",
        )

    return AuthStatus(
        authenticated=False,
        session_valid=False,
    )


@router.get("/login-url", response_model=LoginUrlResponse)
async def get_login_url():
    """
    Get Zerodha login URL for OAuth authentication.

    User should:
    1. Open this URL in browser
    2. Login with Zerodha credentials
    3. Get redirected back with request_token
    4. Call /auth/callback with the request_token
    """
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={settings.kite_api_key}"

    return LoginUrlResponse(
        login_url=login_url,
        callback_url="http://127.0.0.1:5000",
    )


@router.post("/connect", response_model=SuccessResponse)
async def connect_broker(state: AppStateDep, paper_mode: bool = True):
    """
    Connect to broker using saved session.

    Args:
        paper_mode: If True, use paper trading (default)

    Prerequisites:
        Run `python scripts/auth.py` first to authenticate with Zerodha
    """
    # Load access token from session
    access_token = load_access_token()
    session = load_session()

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No valid session found. Run 'python scripts/auth.py' to authenticate.",
        )

    try:
        if paper_mode:
            broker = PaperBroker(
                initial_capital=settings.paper_trading_capital,
                kite_api_key=settings.kite_api_key,
                kite_api_secret=settings.kite_api_secret,
            )
            broker.authenticate(access_token=access_token)
            mode_str = "paper"
        else:
            from backend.broker.zerodha import ZerodhaBroker
            broker = ZerodhaBroker(
                api_key=settings.kite_api_key,
                api_secret=settings.kite_api_secret,
            )
            broker.authenticate(access_token=access_token)
            mode_str = "live"

        state.broker = broker

        user_name = session.get("user_name", "Unknown") if session else "Unknown"
        logger.info(f"Broker connected", mode=mode_str, user=user_name)

        return SuccessResponse(
            success=True,
            message=f"Connected to Zerodha ({mode_str} mode) as {user_name}",
        )

    except Exception as e:
        logger.error(f"Failed to connect broker: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect: {str(e)}",
        )


@router.post("/disconnect", response_model=SuccessResponse)
async def disconnect_broker(state: AppStateDep):
    """
    Disconnect from broker and reset state.
    """
    if state.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disconnect while bot is running. Stop the bot first.",
        )

    state.reset()

    return SuccessResponse(
        success=True,
        message="Disconnected from broker",
    )
