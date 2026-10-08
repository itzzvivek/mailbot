import imaplib
import email
import re
import asyncio
from email.header import decode_header
from typing import Dict, List


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


# Main sync function

def fetch_new_emails_sync(
    gmail_address: str,
    app_password: str,
    filters: List[str],
    last_uid: int = 0,
    max_results: int = 5,
    mark_read: bool = True,
) -> tuple:
    """
    Fetch only emails with UID > last_uid.
    Returns (emails, new_last_uid).
    """
    emails = []
    highest_uid = last_uid
    mail = None

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail_address, app_password)
        mail.select("inbox")

        #First run: bootstrap to current max UID
        if last_uid == 0:
            print("First run — bootstrapping...")
            status, data = mail.uid("search", None, "ALL")  # ✅ "OK" and "ALL"
            if status == "OK" and data and data[0]:
                uids = data[0].split()
                if uids:
                    highest_uid = int(uids[-1])
            print(f"Bootstrapped last_uid={highest_uid}")
            return [], highest_uid

        #Subsequent runs: fetch UID > last_uid
        uid_range = f"{last_uid + 1}:*"

        if not filters or "all" in filters:
            #Native UID search (works reliably with Gmail)
            print(f"UID search: UID {uid_range}")
            status, data = mail.uid("search", None, f"UID {uid_range}")
            if status != "OK":
                print(f"UID search failed: {status}")
                return [], highest_uid
            uid_list = data[0].split() if data and data[0] else []
        else:
            #Gmail-specific filter, then client-side UID filter
            criteria = _build_imap_criteria(filters)
            print(f"🔍 Gmail search: {criteria}")
            status, data = mail.uid("search", None, *criteria)
            if status != "OK":
                print(f"Gmail search failed: {status}")
                return [], highest_uid
            all_uids = [int(u) for u in data[0].split()] if data and data[0] else []
            uid_list = [str(u).encode() for u in all_uids if u > last_uid]

        if not uid_list:
            print("📭 No new messages")
            return [], highest_uid

        # Cap at max_results per cycle (take the newest)
        uid_list = uid_list[-max_results:]
        print(f"📬 Found {len(uid_list)} new messages")

        for uid in uid_list:
            uid_int = int(uid)
            try:
                status, msg_data = mail.uid("fetch", uid, "(RFC822 X-GM-LABELS)")
                if status != "OK":
                    print(f"Fetch failed for UID {uid}: {status}")
                    continue

                raw_email = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email = part[1]
                        break
                if not raw_email:
                    print(f"No raw email for UID {uid}")
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

            except Exception as e:
                print(f"Error parsing UID {uid}: {e}")
                continue
            finally:
                # Always advance highest_UID, even if fetch/parse failed
                if uid_int > highest_uid:
                    highest_uid = uid_int

    except imaplib.IMAP4.error as e:
        print(f"IMAP error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
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

    print(f"✅ Returning {len(emails)} emails (highest UID: {highest_uid})")
    return emails, highest_uid


# Async wrapper

async def fetch_new_emails(
    gmail_address: str,
    app_password: str,
    filters: List[str],
    last_uid: int = 0,
    max_results: int = 5,
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