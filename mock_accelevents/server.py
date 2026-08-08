import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

EXPECTED_KEY = os.environ.get("MOCK_ACCELEVENTS_KEY", "demo-key")
FAIL_ON_WRITE = int(os.environ.get("MOCK_ACCELEVENTS_FAIL_ON_WRITE", "0"))
FAIL_EMAIL = os.environ.get("MOCK_ACCELEVENTS_FAIL_EMAIL", "")
state = {"speakers": {}, "sessions": {}, "writes": 0, "next_speaker": 1, "next_session": 1}


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return self.headers.get("Key") == EXPECTED_KEY

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if not self._auth():
            return self._json(401, {"code": 401, "message": "Unauthorized"})
        path = urlparse(self.path).path
        if path.endswith("/speaker/speakerWithSessions"):
            return self._json(
                200,
                [
                    {
                        **speaker,
                        "sessions": [
                            session
                            for session in state["sessions"].values()
                            if session.get("speakerId") == speaker["id"]
                        ],
                    }
                    for speaker in state["speakers"].values()
                ],
            )
        return self._json(404, {"code": 404, "message": "Not found"})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {"code": 401, "message": "Unauthorized"})
        path = urlparse(self.path).path
        payload = self._body()
        if path.endswith("/speaker"):
            if FAIL_EMAIL and payload.get("email") == FAIL_EMAIL:
                return self._json(503, {"code": 503, "message": "Injected failure"})
            if any(item["email"] == payload.get("email") for item in state["speakers"].values()):
                return self._json(409, {"code": 4068906, "message": "Speaker already exists"})
            state["writes"] += 1
            if FAIL_ON_WRITE and state["writes"] == FAIL_ON_WRITE:
                return self._json(503, {"code": 503, "message": "Injected failure"})
            speaker_id = state["next_speaker"]
            state["next_speaker"] += 1
            state["speakers"][speaker_id] = {"id": speaker_id, **payload}
            return self._json(200, speaker_id)
        if path.endswith("/session"):
            state["writes"] += 1
            if FAIL_ON_WRITE and state["writes"] == FAIL_ON_WRITE:
                return self._json(503, {"code": 503, "message": "Injected failure"})
            session_id = state["next_session"]
            state["next_session"] += 1
            state["sessions"][session_id] = {"id": session_id, **payload}
            return self._json(200, session_id)
        return self._json(404, {"code": 404, "message": "Not found"})

    def do_PUT(self):
        if not self._auth():
            return self._json(401, {"code": 401, "message": "Unauthorized"})
        path = urlparse(self.path).path
        payload = self._body()
        parts = path.strip("/").split("/")
        if len(parts) < 6 or parts[-2] not in {"speaker", "session"}:
            return self._json(404, {"code": 404, "message": "Not found"})
        kind = parts[-2]
        try:
            external_id = int(parts[-1])
        except ValueError:
            return self._json(404, {"code": 404, "message": "Not found"})
        records = state[f"{kind}s"]
        record = records.get(external_id)
        if record is None:
            return self._json(404, {"code": 404, "message": "Not found"})
        if kind == "speaker":
            if payload.get("email") != record.get("email") and record.get("loggedIn"):
                return self._json(
                    409,
                    {
                        "code": 4090121,
                        "message": "User has already logged in at website, can't change email now",
                    },
                )
            if any(
                item_id != external_id and item.get("email") == payload.get("email")
                for item_id, item in records.items()
            ):
                return self._json(
                    409,
                    {"code": 4068906, "message": "Speaker already exists"},
                )
        record.update(payload)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        return


def main():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "9000"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
