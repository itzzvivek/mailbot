import storage

def _use_temp_storage(tmp_path, monkeypatch):
    storage_file = tmp_path / "storage.json"
    monkeypatch.setattr(storage, "STORAGE_FILE", str(storage_file))
    return storage_file

def test_no_file_yet_returns_defaults(tmp_path, monkeypatch):
    _use_temp_storage(tmp_path, monkeypatch)
    assert storage.get_last_seen_uid() is None
    assert storage.get_channel_filters(123) == []
    assert storage.all_watched_channels() == {}

def test_channel_filters_roundtrip(tmp_path, monkeypatch):
    _use_temp_storage(tmp_path, monkeypatch)

    storage.set_channel_filters(123, ["primary", "important"])
    assert storage.get_channel_filters(123) == ["primary", "important"]

    # Overwriting replaces, doesn't append
    storage.set_channel_filters(123, ["social"])
    assert storage.get_channel_filters(123) == ["social"]

def test_last_seen_uid_roundtrip(tmp_path, monkeypatch):
    _use_temp_storage(tmp_path, monkeypatch)

    storage.set_last_seen_uid(12345)
    assert storage.get_last_seen_uid() == 12345

    storage.set_last_seen_uid(67890)
    assert storage.get_last_seen_uid() == 67890

def test_all_watched_channels_excludes_empty_filters(tmp_path, monkeypatch):
    _use_temp_storage(tmp_path, monkeypatch)

    storage.set_channel_filters(1, ["primary"])
    storage.set_channel_filters(2, [])
    storage.set_channel_filters(3, ["important", "social"])

    watched = storage.all_watched_channels()
    assert watched == {
        "1": {"filters": ["primary"]},
        "3": {"filters": ["important", "starred"]},
    }
    assert 2 not in watched

def test_channels_are_independent(tmp_path, monkeypatch):
    _use_temp_storage(tmp_path, monkeypatch)

    storage.set_channel_filters(111, ["primary"])
    storage.set_channel_filters(222, ["important"])

    assert storage.get_channel_filters(111) == ["primary"]
    assert storage.get_channel_filters(222) == ["important"]