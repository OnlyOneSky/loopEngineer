import json

from loopengine.slack import SlackPoster


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload


def test_post_sends_auth_and_returns_ts():
    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"ok": True, "ts": "1700000000.123"})

    poster = SlackPoster("xoxb-token", "C123", urlopen=fake_urlopen)
    ts = poster.post("hello")
    assert ts == "1700000000.123"
    assert captured["url"] == "https://slack.com/api/chat.postMessage"
    assert captured["auth"] == "Bearer xoxb-token"
    assert captured["body"] == {"channel": "C123", "text": "hello"}


def test_post_includes_thread_ts_when_replying():
    captured = {}

    def fake_urlopen(req, timeout=10):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"ok": True, "ts": "child"})

    SlackPoster("t", "C1", urlopen=fake_urlopen).post("reply", thread_ts="root")
    assert captured["body"]["thread_ts"] == "root"


def test_api_error_degrades_to_thread_ts_without_raising():
    def fake_urlopen(req, timeout=10):
        return _FakeResponse({"ok": False, "error": "channel_not_found"})

    ts = SlackPoster("t", "C1", urlopen=fake_urlopen).post("x", thread_ts="root")
    assert ts == "root"   # keeps threading; does not crash the loop


def test_network_error_degrades_gracefully():
    def fake_urlopen(req, timeout=10):
        raise OSError("connection refused")

    ts = SlackPoster("t", "C1", urlopen=fake_urlopen).post("x", thread_ts="root")
    assert ts == "root"
