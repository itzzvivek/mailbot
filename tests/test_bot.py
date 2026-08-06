import asyncio
import bot as bot_module

class FakeChannel:
    def __init__(self):
        self.sent_embed = None

    async def send(self, embed=None):
        self.sent_embed = embed

def test_post_new_mail_build_expected_embed(monkeypatch):
    fake_channel = FakeChannel()
    monkeypatch.setattr(bot_module.bot, "get_channel", lambda channel_id: fake_channel)

    message ={
        "from": "Alice <alice@example.com>",
        "subject": "Budget review",
        "snippet": "Please see attached numbers ahead of Thursday's call",
        "data": "Mon, 1 Jan 2026 10:00:00 +0000",
        "link": "https://mail.google.com/mail/u/0/#inbox/123"
    }

    asyncio.run(bot_module.post_new_mail(channel_id=999, message=message))

    embed = fake_channel.sent_embed
    assert embed is not None
    assert embed.title == "Budget review"
    assert "Please see attached numbers" in embed.description
    assert embed.url == message["link"]
    assert embed.author.name == "Alice <alice@example.com>"


def test_post_new_mail_handles_missing_subject(monkeypatch):
    fake_channel = FakeChannel()
    monkeypatch.setattr(bot_module.bot, "get_channel", lambda cid: fake_channel)

    message = {
        "from": "Bob <bob@example.com>",
        "subject": "",
        "snippet": "",
        "date": "",
        "link": "https://mail.google.com/mail/u/0/#inbox/456"
    }

    asyncio.run(bot_module.post_new_mail(channel_id=999, message=message))

    embed = fake_channel.sent_embed
    assert embed.title == "(no subject)"
