"""OpenAI-compatible chat completions that must answer with one strict JSON object."""
from dataclasses import dataclass
import http.client
import json
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.request import Request, urlopen

USER_AGENT = "shutong/0.1 (https://github.com/Juhuaaaa/shutong)"


class AiError(Exception):
    """The request failed, or the model did not answer with a valid JSON object."""

    def __init__(self, message: str, raw: Optional[str] = None) -> None:
        super().__init__(message)
        self.raw = raw  # the model's content when it was received, for the audit log


@dataclass(frozen=True)
class AiSettings:
    base_url: str
    api_key: str
    model: str
    threshold: float = 0.85
    timeout: float = 60


def strict_json(value: Any, label: str) -> Any:
    """json.loads that rejects NaN/Infinity and non-text input."""
    def reject_constant(constant):
        raise ValueError("non-finite JSON number: {0}".format(constant))

    try:
        text = value.decode("utf-8") if isinstance(value, bytes) else value
        if not isinstance(text, str):
            raise TypeError("JSON input must be text")
        return json.loads(text, parse_constant=reject_constant)
    except (TypeError, UnicodeDecodeError, ValueError) as error:
        raise AiError("{0} is not valid JSON".format(label)) from error


class OpenAICompatProvider:
    def __init__(self, settings: AiSettings, opener: Callable[..., Any] = urlopen) -> None:
        self.settings = settings
        self._opener = opener

    @property
    def model(self) -> str:
        return self.settings.model

    def complete_json(self, system: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        body = {
            "model": self.settings.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            return self._complete(system, body)
        except (ValueError, http.client.HTTPException) as error:  # bad base_url, truncated body
            if isinstance(error, AiError):
                raise
            raise AiError("AI request failed: {0}".format(error)) from error

    def _complete(self, system: str, body: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        request = Request(
            self.settings.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer {0}".format(self.settings.api_key),
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.settings.timeout) as response:
                raw_envelope = response.read()
        except OSError as error:
            raise AiError("AI request failed: {0}".format(error)) from error
        envelope = strict_json(raw_envelope, "AI response")
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise AiError("AI response has an invalid message envelope") from error
        if not isinstance(content, str):
            raise AiError("AI message content must be a string")
        try:
            parsed = strict_json(content, "AI message content")
        except AiError as error:
            raise AiError(str(error), raw=content) from error
        if not isinstance(parsed, dict):
            raise AiError("AI message content must be a JSON object", raw=content)
        return parsed, content
