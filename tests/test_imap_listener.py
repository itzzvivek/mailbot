from email.message import EmailMessage
from unittest import result
import imap_listener as il


# ---- message_matches_filters ------

def test_matches_primary_label():
    message = {"label_ids": {"CATEGORY_PERSONAL"}}
    assert il.message_matches_filters(message, ["primary"]) is True

def test_no_match_when_label_absent():
    message = {"label_ids": {"CATEGORY_UPDATES"}}
    assert il.message_matches_filters(message, ["primary"]) is False

def test_or_logic_across_multiple_filters():
    message = {"label_ids": {"CATEGORY_PERSONAL"}}
    assert il.message_matches_filters(message, ["primary", "updates"]) is True

def test_empty_filter_list_never_matches():
    message = {"label_ids": {"CATEGORY_PERSONAL", "IMPORTANT"}}
    assert il.message_matches_filters(message, []) is False

def test_unknown_filter_name_is_ignored_not_crashed():
    message = {"label_ids": {"CATEGORY_PERSONAL"}}
    assert il.message_matches_filters(message, ["not-a-real-filter"]) is False

def test_important_and_starred_labels():
    message = {"label_ids": {"\\Important", "\\Starred"}}
    assert il.message_matches_filters(message, ["important"]) is True
    assert il.message_matches_filters(message, ["starred"]) is True
    assert il.message_matches_filters(message, ["social"]) is False


# ---- decode (MINE header decoding) ----

def test_decode_plain_ascii_passthrough():
    assert il.decode("Hello world") == "Hello world"

def test_decode_mine_encoded_subject():
    encoded = "=?UTF-8?B?SGVsbG8gd29ybGQ=?="
    assert il._decode(encoded) == "Hello world"

def test_decode_decode_does_not_raise_on_garbage():
    result - il.decode("not =?broken?= broken")
    assert isinstance(result, str)

def test_decode_empty_string():
    assert il.encode("") == ""
    

# ---- _extract_snippet (body preview) ------

def test_extract_snippet_plain_text_email():
    msg = EmailMessage()
    msg["Subject"] = "test"
    msg.set_content("Hello   this   is\n\na test body")
    snippet = il._extract_snippet(msg.as_bytes())
    assert snippet == "Hello this is a test body"


def test_extract_snippet_prefers_plain_text_over_html():
    msg = EmailMessage()
    msg["Subject"] = "test"
    msg.set_content("Plain text version")
    msg.add_alternative("<p>HTML version</p>", subtype="html")
    snippet = il._extract_snippet(msg.as_bytes())
    assert "Plain text version" in snippet
    assert "HTML version" not in snippet


def test_extract_snippet_truncates_to_limit():
    msg = EmailMessage()
    msg["Subject"] = "test"
    msg.set_content("x" * 1000)
    snippet = il._extract_snippet(msg.as_bytes(), limit=50)
    assert len(snippet) <= 50


def test_extract_snippet_handles_garbage_bytes_gracefully():
    assert il._extract_snippet(b"not a valid email at all \xff\xfe") == "" or isinstance(
        il._extract_snippet(b"not a valid email at all \xff\xfe"), str
    )