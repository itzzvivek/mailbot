# oauth_server.py
import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv

from database import create_user, init_db

load_dotenv()

app = FastAPI(title="Gmail OAuth Server")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/oauth")
async def oauth_start(discord_id: str):
    """Redirect user to Google OAuth consent screen"""
    if not discord_id:
        raise HTTPException(status_code=400, detail="Missing discord_id")

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        "response_type=code&"
        "scope=https://www.googleapis.com/auth/gmail.readonly&"
        f"state={discord_id}&"
        "access_type=offline&"
        "prompt=consent"
    )
    return RedirectResponse(auth_url)


@app.get("/oauth/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    """Handle Google OAuth callback"""
    if error:
        return HTMLResponse(f"<h1>Authorization failed</h1><p>{error}</p>")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    discord_id = int(state)

    # Exchange code for tokens
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    )

    if response.status_code != 200:
        return HTMLResponse(
            f"<h1>Token exchange failed</h1><pre>{response.text}</pre>"
        )

    tokens = response.json()
    refresh_token = tokens.get("refresh_token")

    if not refresh_token:
        return HTMLResponse(
            "<h1>⚠️ No refresh token received</h1>"
            "<p>Try removing the app from your Google account and reconnecting.</p>"
        )

    # Store in database
    await create_user(discord_id, refresh_token)

    return HTMLResponse("""
        <html>
        <head><title>Connected!</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>Gmail Connected!</h1>
            <p>You can now close this tab and return to Discord.</p>
            <p>Use <code>/setchannel</code> to set where notifications go.</p>
        </body>
        </html>
    """)