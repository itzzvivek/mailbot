import email
import logging
import time
from email.header import decode_header, make_header

from imapclient import IMAPClient

from config import (
    GMAIL_ADDRESS,
    GMAIL_APP_PASSWORD,
    GMAIL_FILTER_OPTIONS,
    IMAP_HOST,
    IMAP_IDLE_TIMEOUT_SECONDS,
    IMAP_RECONNECT_DELAY_SECONDS,
)
from storage import get_last_seen_uid, set_last_seen_uid, all_watched_channels

log = logging.getLogger("imap_listener")


def _decode(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value or ""


def _extract_snippet(raw_bytes: bytes, limit: int = 300) -> str:
    try:
        msg = email.message_from_bytes(raw_bytes)
        text = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and not part.get_filename():
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                    break
        else:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace") if payload else ""
        return " ".join(text.split())[:limit]
    except Exception:
        return ""


def _connect() -> IMAPClient:
    client = IMAPClient(IMAP_HOST, ssl=True, use_uid=True)
    client.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    client.select_folder("INBOX")
    return client


def _fetch_summary(client: IMAPClient, uid: int) -> dict:
    data = client.fetch([uid], ["ENVELOPE", "X-GM-LABELS", "X-GM-THRID", "RFC822"])
    item = data[uid]
    envelope = item[b"ENVELOPE"]

    raw_labels = item.get(b"X-GM-LABELS", ())
    labels = {(l.decode() if isinstance(l, bytes) else str(l)) for l in raw_labels}

    thread_id = item.get(b"X-GM-THRID")
    raw_message = item.get(b"RFC822", b"")

    from_addr = envelope.from_[0] if envelope.from_ else None
    if from_addr:
        name = _decode(from_addr.name.decode()) if from_addr.name else ""
        mailbox = from_addr.mailbox.decode() if from_addr.mailbox else "unknown"
        host = from_addr.host.decode() if from_addr.host else ""
        from_str = f"{name} <{mailbox}@{host}>".strip() if name else f"{mailbox}@{host}"
    else:
        from_str = "Unknown sender"

    return {
        "uid": uid,
        "from": from_str,
        "subject": _decode(envelope.subject.decode()) if envelope.subject else "(no subject)",
        "date": str(envelope.date) if envelope.date else "",
        "snippet": _extract_snippet(raw_message),
        "label_ids": labels,
        "link": (
            f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"
            if thread_id else "https://mail.google.com/mail/u/0/#inbox"
        ),
    }


def message_matches_filters(message: dict, active_filters: list[str]) -> bool:
    """active_filters is a list of friendly names, e.g. ['primary', 'important']."""
    labels = message["label_ids"]
    for f in active_filters:
        gmail_label = GMAIL_FILTER_OPTIONS.get(f)
        if gmail_label and gmail_label in labels:
            return True
    return False


def run_forever(on_new_message):
    """
    Blocking loop, meant to run in a background thread for the life of the process.
    on_new_message: plain (non-async) callable(channel_id: int, message: dict).
    """
    while True:
        try:
            client = _connect()
            log.info("Connected to Gmail IMAP, watching INBOX")

            last_uid = get_last_seen_uid()
            if last_uid is None:
                # First run ever: don't replay the whole inbox, just start from "now".
                existing = client.search("ALL")
                last_uid = max(existing) if existing else 0
                set_last_seen_uid(last_uid)
                log.info("No prior state, starting from UID %s", last_uid)

            while True:
                client.idle()
                try:
                    client.idle_check(timeout=IMAP_IDLE_TIMEOUT_SECONDS)
                finally:
                    client.idle_done()

                new_uids = sorted(uid for uid in client.search("ALL") if uid > last_uid)
                if not new_uids:
                    continue  # keepalive cycle or a change that wasn't a new message

                watched = all_watched_channels()

                for uid in new_uids:
                    last_uid = uid
                    set_last_seen_uid(last_uid)

                    if not watched:
                        continue  # nobody's listening, don't bother fetching details

                    try:
                        summary = _fetch_summary(client, uid)
                    except Exception:
                        log.exception("Failed to fetch UID %s", uid)
                        continue

                    for channel_id, filters in watched.items():
                        if message_matches_filters(summary, filters):
                            on_new_message(channel_id, summary)

        except Exception:
            log.exception("IMAP connection dropped, reconnecting in %ss", IMAP_RECONNECT_DELAY_SECONDS)
            time.sleep(IMAP_RECONNECT_DELAY_SECONDS)
