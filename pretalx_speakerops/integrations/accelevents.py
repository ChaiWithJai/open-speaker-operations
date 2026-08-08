import json
import time
import uuid
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AcceleventsError(RuntimeError):
    def __init__(self, message, code=None, status=None):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class AcceleventsClient:
    base_url: str
    event_url: str
    credential: str
    auth_header: str = "Key"
    retries: int = 2
    timeout: float = 5
    last_request_id: str = field(default="", init=False)

    def _request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        self.last_request_id = str(uuid.uuid4())
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=body,
            headers={
                self.auth_header: self.credential,
                "Content-Type": "application/json",
                "X-Request-ID": self.last_request_id,
            },
            method=method,
        )
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode()
                    return json.loads(raw) if raw else None
            except HTTPError as error:
                raw = error.read().decode()
                try:
                    detail = json.loads(raw)
                except json.JSONDecodeError:
                    detail = {}
                code = detail.get("code")
                if code in {4068906, 4090121}:
                    raise AcceleventsError(
                        detail.get("message", str(error)),
                        code=code,
                        status=error.code,
                    ) from error
                if error.code in {400, 401, 403, 404} or attempt == self.retries:
                    raise AcceleventsError(
                        detail.get("message", str(error)), code=code, status=error.code
                    ) from error
            except URLError as error:
                if attempt == self.retries:
                    raise AcceleventsError(str(error)) from error
            time.sleep(0.05 * (2**attempt))

    def create_speaker(self, payload):
        return self._request("POST", f"/rest/host/event/{self.event_url}/speaker", payload)

    def create_session(self, payload):
        return self._request("POST", f"/rest/host/event/{self.event_url}/session", payload)

    def update_speaker(self, external_id, payload):
        return self._request(
            "PUT", f"/rest/host/event/{self.event_url}/speaker/{external_id}", payload
        )

    def update_session(self, external_id, payload):
        return self._request(
            "PUT", f"/rest/host/event/{self.event_url}/session/{external_id}", payload
        )

    def speakers_with_sessions(self):
        return self._request(
            "GET", f"/rest/host/event/{self.event_url}/speaker/speakerWithSessions"
        )
