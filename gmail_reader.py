import asyncio
import os
import base64
from asyncio import timeout
from idlelib.rpc import response_queue

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
    print(f"Token refresh failed: {response.text}")
    return None

def build_query(filters: List[str]) -> str:
    """Build Gmail search query from user filters"""
    if not filters:
        return "is:unread"

    if "all" in filters:
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

def _get_header(headers: List[Dict], name: str) -> Optional[str]:
    """Extract a specific header from Gmail message headers"""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return None

def _extract_body_preview(payload: dict, max_length: int = 300) -> str:
    """Extract plain-text preview from Gmail message payload"""
    try:
        if "body" in payload and payload.get("mimeType", "") == "text/plain":
            data = payload["body"].get["data"]
            if data:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                return decoded[:max_length].replace("\n", " ").strip()

        parts = payload.get("parts", [])
        for part in parts:
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    return decoded[:max_length].replace("\n", " ").strip()

            if mime.startswith("multipart"):
                nested = _extract_body_preview(part, max_length)
                if nested:
                    return nested
    except Exception as e:
        print(f"Error extracting preview: {e}")


async def _fetch_message_list(access_token, query, max_results):
    """Internal function to fetch the list of message IDs."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params={"q": query, "maxResults": max_results}
    )

    if response.status_code != 200:
        response.raise_for_status()
    return response.json().get("messages", [])

async def _fetch_message_detail(access_token: str, msg_id: str) -> Optional[Dict]:
    """Internal: Fetch full message details"""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(
            f"https://gmail/googleapis.com/gmail/v1/users/me/messages/{msg_id}",
            headers=headers,
            params={"format": "full"},
            timeout=15
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching message: {msg_id}:{e}")
        return None

async def _mark_as_read(access_token: str, msg_id: str) -> bool:
    """Internal: Mark message as read (remove UNREAD label)"""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/modify",
            headers=headers,
            json={"removeLabelIds": ["UNREAD"]},
            timeout=10
        )
        return response.status_code == 200
    except requests.RequestException as e:
        print(f"Failed to mark {msg_id} ad read: {e}")
        return False

async def fetch_new_emails(
    refresh_token: str,
    filters: List[str],
    max_results: int = 5,
    mark_read: bool = True
) -> List[Dict]:
    """Fetch new unread emails from Gmail"""
    access_token = await refresh_access_token(refresh_token)
    if not access_token:
        print("Could not obtain access token")
        return []

    query = build_query(filters)
    print(f"Gmail query: {query}")

    messages = []
    for attempt in range(3):
        try:
            messages = await _fetch_message_list(access_token, query, max_results)
            if messages:
                print(f"Found {len(messages)} messages")
                break
            else:
                print(f"No messages found (attempt {attempt + 1})/3")
        except requests.HTTPError as e:
            print(f"Attempt {attempt + 1} failed: {e}")

        if attempt < 2:
            await asyncio.sleep(3)

    if not messages:
        return []

    emails = []
    for msg in messages:
        msg_id = msg.get("id")
        if not msg_id:
            continue

        details = await _fetch_message_detail(access_token, msg_id)
        if not details:
            continue

        try:
            header_list=details.get("headers", []).get("headers", [])
            subject= _get_header(header_list, "Subject") or "(no subject)"
            sender= _get_header(header_list, "From") or "unknown"
            date= _get_header(header_list, "Date") or ""

            preview = _extract_body_preview(details.get("payload", {}), 300)

            if not preview:
                preview = details.get("snippet", "")[:300]

            labels = details.get("labels", [])

            emails.append({
                "id": msg_id,
                "subject": subject,
                "from": sender,
                "preview": preview,
                "date": date,
                "labels": labels,
            })

            if mark_read:
                await _mark_as_read(access_token, msg_id)

        except requests.HTTPError as e:
            print(f"Error parsing message {msg_id}: {e}")
            continue

    print(f"Returning {len(emails)} emails")
    return emails