import imaplib
import email
from email.header import decode_header
from hmac import new
from typing import Dict, List
from datetime import datetime

def _decode_header_value(raw: str) -> str:
    """Decode RFC 2047 encoded header value."""
    if not raw:
        return ''

    try:
        parts = decode_header(raw)
        decoded = ""
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded = content.decode(charset or "utf-8", errors="ignore")
            else:
                decoded += content
        return decoded.strip()
    except Exception:
        return raw

def _extract_preview(msg, max_length: int = 300) -> str:
    """Extract plain text preview from email message"""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        text = payload.decode("utf-8", errors="ignore")
                        return text[:max_length].replace("\n", " ").strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                text = payload.decode("utf-8", errors="ignore")
                return text[:max_length].replace("\n", " ").strip()
    except Exception as e:
        print(f"⚠️ Preview extraction failed: {e}")
    return ""


def _build_imap_criteria(filters: List[str]) -> list:
    """
    Gmail IMAP uses Gmail's own X-GM-RAW extension.
    Returns criteria list for mail.search().
    """
    if not filters or "all" in filters:
        return ["UNSEEN"]

    parts = []
    if "primary" in filters:
        parts.append("category:primary")
    if "important" in filters:
        parts.append("is:important")
    if "social" in filters:
        parts.append("category:social")
    if "updates" in filters:
        parts.append("category:updates")
    if "promotions" in filters:
        parts.append("category:promotions")
    if "forums" in filters:
        parts.append("category:forums")

    if not parts:
        return ["UNSEEN"]

    # Combine using Gmail's raw search via X-GM-RAW
    query = "is:unread " + " ".join(parts)
    return ["X-GM-RAW", f'"{query}"']


def fetch_new_emails_sync(
    gmail_address: str,
    app_password: str,
    filters: List[str],
    max_results: int = 5,
    mark_read: bool = True
) -> List[Dict]:
    """
    Synchronous IMAP fetch. Call inside an executor from async code.

    Returns list of dicts: {id, subject, from, preview, date}
    """
    emails = []
    mail = None

    try:
        # Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail_address, app_password)

        # Select inbox (read-only=False so we can mark as read)
        mail.select("inbox")

        # Build search criteria
        criteria = _build_imap_criteria(filters)
        print(f"IMAP criteria: {criteria}")

        status, data = mail.search(None, *criteria)
        if status != "OK":
            print(f"IMAP search failed: {status}")
            return []

        msg_ids = data[0].split()
        if not msg_ids:
            print("No messages found")
            return []

        # Take the most recent N (Gmail returns oldest first)
        msg_ids = msg_ids[-max_results:]
        print(f"Found {len(msg_ids)} messages")

        for msg_id in msg_ids:
            try:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                sender = _decode_header_value(msg.get("From", "Unknown"))
                date = msg.get("Date", "")
                preview = _extract_preview(msg, 300)

                emails.append({
                    "id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                    "subject": subject,
                    "from": sender,
                    "preview": preview,
                    "date": date,
                })

                # Mark as read
                if mark_read:
                    mail.store(msg_id, "+FLAGS", "\\Seen")

            except Exception as e:
                print(f"Error parsing message {msg_id}: {e}")
                continue

    except imaplib.IMAP4.error as e:
        print(f"IMAP login/search error: {e}")
    except Exception as e:
        print(f"Unexpected IMAP error: {e}")
    finally:
        if mail:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

    print(f"Returning {len(emails)} emails")
    return emails


async def fetch_new_emails(
    gmail_address: str,
    app_password: str,
    filters: List[str],
    max_results: int = 5,
    mark_read: bool = True
) -> List[Dict]:
    """
    Async wrapper around the synchronous IMAP call.
    Runs IMAP in a thread so it doesn't block the event loop.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        fetch_new_emails_sync,
        gmail_address,
        app_password,
        filters,
        max_results,
        mark_read,
    )