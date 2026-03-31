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


@router.get("/callback")
async def auth_callback(request_token: str, action: str = "login", status: str = "success"):
    """
    OAuth callback from Zerodha.

    After user logs in on Zerodha, they are redirected here with a request_token.
    This exchanges it for an access_token and saves the session.
    """
    if status != "success" or not request_token:
        raise HTTPException(
            status_code=400,
            detail="Authentication failed or cancelled.",
        )

    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.kite_api_key)
        data = kite.generate_session(
            request_token=request_token,
            api_secret=settings.kite_api_secret,
        )

        access_token = data["access_token"]

        # Save session
        from backend.broker.session import save_access_token
        save_access_token(access_token, data)

        logger.info(f"OAuth callback: authenticated as {data.get('user_name')}")

        # Return HTML page that auto-closes or redirects to dashboard
        import html
        from fastapi.responses import HTMLResponse

        safe_name = html.escape(data.get("user_name", "Trader"))
        return HTMLResponse(content=f"""
        <html>
        <head><title>Authenticated</title></head>
        <body style="font-family:sans-serif;text-align:center;padding:50px;background:#0a0a0a;color:#e5e5e5;">
            <h1 style="color:#22c55e;">Authenticated</h1>
            <p>Welcome, {safe_name}</p>
            <p>You can close this tab and return to the dashboard.</p>
            <script>setTimeout(()=>window.close(), 3000);</script>
        </body>
        </html>
        """)

    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content="<h1>Authentication Failed</h1><p>Could not authenticate with Zerodha. Please try again.</p>",
            status_code=500,
        )


@router.post("/connect", response_model=SuccessResponse)
async def connect_broker(state: AppStateDep, paper_mode: bool = True):
    """
    Connect to broker using saved session.

    Falls back to standalone paper broker (no live market data)
    when Kite session is expired. This ensures the dashboard
    always works for visitors, even without authentication.
    """
    access_token = load_access_token()
    session = load_session()

    try:
        if paper_mode:
            broker = PaperBroker(
                initial_capital=settings.paper_trading_capital,
                kite_api_key=settings.kite_api_key,
                kite_api_secret=settings.kite_api_secret,
            )

            if access_token:
                # Valid Kite session — paper broker with real market data
                broker.authenticate(access_token=access_token)
                user_name = session.get("user_name", "Unknown") if session else "Unknown"
                mode_str = "paper+live_data"
                message = f"Paper trading with live market data as {user_name}"
            else:
                # No valid session — standalone paper broker (saved data only)
                broker.authenticate()
                mode_str = "paper_only"
                message = "Paper trading mode (Kite session expired — using saved data)"

            state.broker = broker
            logger.info("Broker connected", mode=mode_str)

            return SuccessResponse(success=True, message=message)

        else:
            if not access_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Live trading requires valid Kite session.",
                )

            from backend.broker.zerodha import ZerodhaBroker
            broker = ZerodhaBroker(
                api_key=settings.kite_api_key,
                api_secret=settings.kite_api_secret,
            )
            broker.authenticate(access_token=access_token)
            state.broker = broker

            user_name = session.get("user_name", "Unknown") if session else "Unknown"
            logger.info("Broker connected", mode="live", user=user_name)
            return SuccessResponse(
                success=True,
                message=f"Connected to Zerodha (live mode) as {user_name}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect broker: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to broker. Check session and try again.",
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
