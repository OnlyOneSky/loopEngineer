"""Slack connector — posts the run's status stream to a channel thread.

One-directional (post only); the loop never reads from Slack, so there is no
approval gate or trigger here — just visibility. Uses the stdlib so the
prototype stays dependency-free. Network/API failures degrade to a printed
warning and never break the loop; a failed post returns the current thread ts
so later replies still thread under whatever root did land.
"""
import json
import urllib.error
import urllib.request

API_URL = "https://slack.com/api/chat.postMessage"


class SlackPoster:
    """Thin `chat.postMessage` client. `urlopen` is injectable for tests."""

    def __init__(self, token: str, channel: str, urlopen=urllib.request.urlopen):
        self._token = token
        self._channel = channel
        self._urlopen = urlopen

    def post(self, text: str, thread_ts: str | None = None) -> str | None:
        payload = {"channel": self._channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._token}",
                     "Content-Type": "application/json; charset=utf-8"},
            method="POST")
        try:
            raw = self._urlopen(req, timeout=10).read().decode("utf-8")
            resp = json.loads(raw)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            print(f"[slack] post failed: {exc}", flush=True)
            return thread_ts
        if not resp.get("ok"):
            print(f"[slack] api error: {resp.get('error')}", flush=True)
            return thread_ts
        return resp.get("ts", thread_ts)
