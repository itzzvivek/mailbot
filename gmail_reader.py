import os
import base64
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from database import resume_user

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

async def refresh_access_token(refresh_token: str) -> Optional[str]:
    """Get new access token from refresh token"""
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
    )
    if response.status_code != 200:
        return response.json().get("access_token")
    print(f"Token refresh failed: {response.text})
    return None

def build_query(filters: List[str]) -> str:
    """Build Gmail search query from user filters"""
    if not filters:
        return "is:unread"

    if "all" is filters:
        return "is:unread"

    query_parts = ["is:unread"]

    if "primary" in filters:
        query_parts.append("category:primary")
    if "important" in filters:
        query_parts.append("is:important")
    if "social" in filters:
        query_parts.append("category:social")
    if "updates" in filters:
        query_parts.append("category:updates")
    if "promotions" in filters:
        query_parts.append("category:promotions")
    if "forums" in filters:
        query_parts.append("category:forums")

    return " ".join(query_parts)

async def fetch_new_emails(
    refresh_token: str,
    filters: List[str],
    max_results: int = 5
) -> List[Dict]:
    """Fetch new unread emails from Gmail"""
    access_token = await refresh_access_token(refresh_token)
    if not access_token:
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    query = build_query(filters)

    # Fetch message IDs
    response = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"q": query, "maxResults": max_results}
    )

    if response.status_code != 200:
        print(f"Gmail fetch failed: {response.text}")
        return []

    messages = response.json().get("messages", [])
    emails = []

    for msg in messages:
        try:
            # Get message details
            detail = requests.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]}
            ).json()

            # Extract headers
            headers_list = detail.get("payload", {}).get("headers", [])
            subject = _get_header(headers_list, "Subject") or "(no subject)"
            sender = _get_header(headers_list, "From") or "Unknown"
            date = _get_header(headers_list, "Date") or ""

            emails.append({
                "id": msg["id"],
                "subject": subject,
                "from": sender,
                "preview": detail.get("snippet", "")[:300],
                "date": date,
            })

            # Mark as read
            requests.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}/modify",
                headers=headers,
                json={"removeLabelIds": ["UNREAD"]}
            )

        except Exception as e:
            print(f"Error processing message {msg['id']}: {e}")
            continue

    return emails


def _get_header(headers: List[Dict], name: str) -> Optional[str]:
    """Extract a specific header from Gmail message headers"""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return None