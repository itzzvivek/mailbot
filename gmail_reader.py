import imaplib
import email
import re
import asyncio
from email.header import decode_header
from typing import Dict, List
from datetime import datetime, timedelta

# Header / body helpers
def _decode_header_value(raw: str) -> str:
    """Decode RFC 2047 encoded header value."""
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
        decoded = ""
        for content, charset in parts:
            if isinstance(content, bytes):
                decoded += content.decode(charset or "utf-8", errors="ignore")
            else:
                decoded += content
        return decoded.strip()
    except Exception:
        return raw


def _extract_preview(msg, max_length: int = 300) -> str:
    """Extract plain text preview from email message."""
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


# Gmail label parsing

def _extract_gmail_labels(msg_data) -> List[str]:
    """
    Parse X-GM-LABELS response from IMAP fetch.
    Gmail returns labels like:
        (\\Inbox \\Important "Category Primary" "Category Updates")
    Returns readable labels like: ['Primary', 'Updates', 'Important']
    """
    labels = []
    for part in msg_data:
        if not isinstance(part, tuple) or len(part) == 0:
            continue
        part_str = part[0].decode(errors="ignore") if isinstance(part[0], bytes) else str(part[0])

        #FIXED: process parts that DO contain X-GM-LABELS
        if "X-GM-LABELS" not in part_str:
            continue

        # Extract quoted labels and bare flags
        matches = re.findall(r'"([^"]+)"|(\\\w+)', part_str)
        for quoted, flag in matches:
            label = quoted or flag
            if not label:
                continue

            clean = label.lstrip("\\").strip()

            # Skip boring system flags
            if clean.lower() in ("inbox", "unread", "seen", "sent", "draft", "starred"):
                if clean.lower() == "starred":
                    labels.append("Starred")
                continue

            # "Category Updates" → "Updates"
            if clean.lower().startswith("category "):
                clean = clean.split(" ", 1)[1]

            labels.append(clean.capitalize())

        break

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for l in labels:
        if l not in seen:
            seen.add(l)
            unique.append(l)
    return unique


# Search criteria builder
def _build_imap_criteria(filters: List[str]) -> list:
    """Build Gmail IMAP search criteria using X-GM-RAW extension."""
    if not filters or "all" in filters:
        return ["ALL"]  # not UNSEEN — we want UID-based, not flag-based

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
        return ["ALL"]

    query = "is:unread " + " ".join(parts)
    return ["X-GM-RAW", f'"{query}"']


def fetch_new_emails_sync(
    gmail_address: str,
    app_password: str,
    filters: List[str],
    last_uid: int = 0,
    max_results: int = 20,
    mark_read: bool = True,
) -> tuple:
    """
    Fetch emails.

    - If last_uid == 0: fetch TODAY'S emails (bootstrap mode)
    - Else:             fetch only emails with UID > last_uid

    Returns (emails, new_last_uid).
    """
    emails = []
    highest_uid = last_uid
    mail = None

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail_address, app_password)
        mail.select("inbox")

        # ─── BOOTSTRAP MODE: fetch today's emails ───
        if last_uid == 0:
            print("Bootstrap mode — fetching today's emails")

            # Gmail IMAP date format: DD-Mon-YYYY
            today = datetime.now().strftime("%d-%b-%Y")

            # Combine user filters with date filter
            criteria = _build_imap_criteria(filters)

            # For X-GM-RAW, append "after:" into the query string
            if criteria and criteria[0] == "X-GM-RAW":
                # criteria looks like: ["X-GM-RAW", '"is:unread category:primary"']
                raw_query = criteria[1].strip('"')
                raw_query = f"{raw_query} after:{today}"
                search_args = ["X-GM-RAW", f'"{raw_query}"']
            else:
                # Standard IMAP: SINCE date
                search_args = criteria + ["SINCE", today]

            # Use UID SEARCH so we get UIDs directly
            status, data = mail.uid("search", None, *search_args)
            if status != "OK":
                print(f"Bootstrap search failed: {status}")
                return [], 0

            uids = data[0].split()
            if not uids:
                print("No emails today")
                # Set watermark to current max so we don't re-scan
                status, data = mail.uid("search", None, "ALL")
                if status == "OK" and data[0]:
                    all_uids = data[0].split()
                    if all_uids:
                        highest_uid = int(all_uids[-1])
                return [], highest_uid

            # Cap to max_results (most recent first)
            uids = uids[-max_results:]
            print(f"Bootstrap: {len(uids)} emails from today")

        # ─── INCREMENTAL MODE: UIDs > last_uid ───
        else:
            criteria = _build_imap_criteria(filters)
            uid_range = f"{last_uid + 1}:*"

            # UID SEARCH with the range
            # if criteria and criteria[0] == "X-GM-RAW":
            #     raw_query = criteria[1].strip('"')
            #     raw_query = f"{raw_query} UID {uid_range}"
            #     search_args = ["X-GM-RAW", f'"{raw_query}"']
            # else:
            search_args = criteria + [f"UID {uid_range}"]

            status, data = mail.uid("search", None, *search_args)
            if status != "OK":
                print(f"Incremental search failed: {status}")
                return [], highest_uid

            all_uids = data[0].split()
            new_uids = [u for u in all_uids if int(u) > last_uid]
            if not new_uids:
                print("No new emails")
                return [], highest_uid

            uids = new_uids[-max_results:]
            print(f"Found {len(uids)} new emails")

        # ─── FETCH EACH EMAIL ───
        for uid in uids:
            uid_int = int(uid)
            try:
                status, msg_data = mail.uid("fetch", uid, "(RFC822 X-GM-LABELS)")
                if status != "OK":
                    continue

                raw_email = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email = part[1]
                        break
                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                subject = _decode_header_value(msg.get("Subject", "(no subject)"))
                sender = _decode_header_value(msg.get("From", "Unknown"))
                date = msg.get("Date", "")
                preview = _extract_preview(msg, 300)
                labels = _extract_gmail_labels(msg_data)

                emails.append({
                    "id": str(uid_int),
                    "uid": uid_int,
                    "subject": subject,
                    "from": sender,
                    "preview": preview,
                    "date": date,
                    "labels": labels,
                })

                if mark_read:
                    mail.uid("store", uid, "+FLAGS", "\\Seen")

                if uid_int > highest_uid:
                    highest_uid = uid_int

            except Exception as e:
                print(f"Error parsing UID {uid}: {e}")
                continue

    except imaplib.IMAP4.error as e:
        print(f"IMAP error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        if mail:
            try: mail.close()
            except Exception: pass
            try: mail.logout()
            except Exception: pass

    print(f"Returning {len(emails)} emails (highest UID: {highest_uid})")
    return emails, highest_uid

# Async wrapper

async def fetch_new_emails(
    gmail_address: str,
    app_password: str,
    filters: List[str],
    last_uid: int = 0,
    max_results: int = 20,
    mark_read: bool = True,
) -> tuple:
    """Async wrapper — runs blocking IMAP in a thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        fetch_new_emails_sync,
        gmail_address,
        app_password,
        filters,
        last_uid,
        max_results,
        mark_read,
    )