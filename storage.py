"""
Tiny JSON-file storage. Good enough for a single-user / small-server bot.
Swap this for SQLite/Postgres if you outgrow it.

Shape of storage.json:
{
  "last_seen_uid": 4821,
  "channels": {
    "<discord_channel_id>": {
      "filters": ["primary", "important"]
    }
  }
}
"""
import json
import os
import threading

from config import STORAGE_FILE

_lock = threading.Lock()


def _load() -> dict:
    if not os.path.exists(STORAGE_FILE):
        return {"last_seen_uid": None, "channels": {}}
    with open(STORAGE_FILE, "r") as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(STORAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_last_seen_uid() -> int | None:
    with _lock:
        return _load().get("last_seen_uid")


def set_last_seen_uid(uid: int) -> None:
    with _lock:
        data = _load()
        data["last_seen_uid"] = uid
        _save(data)


def get_channel_filters(channel_id: int) -> list[str]:
    with _lock:
        data = _load()
        entry = data["channels"].get(str(channel_id))
        return entry["filters"] if entry else []


def set_channel_filters(channel_id: int, filters: list[str]) -> None:
    with _lock:
        data = _load()
        data["channels"].setdefault(str(channel_id), {})
        data["channels"][str(channel_id)]["filters"] = filters
        _save(data)


def all_watched_channels() -> dict:
    """Returns {channel_id: [filters]} for every channel that has filters set."""
    with _lock:
        data = _load()
        return {
            int(cid): entry["filters"]
            for cid, entry in data["channels"].items()
            if entry.get("filters")
        }
