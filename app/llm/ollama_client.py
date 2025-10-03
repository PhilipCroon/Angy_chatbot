"""Direct Ollama chat client used by the Angy intake chatbot."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Dict, Optional


class OllamaChatLLM:
    """Wrapper around a locally hosted Ollama chat model."""

    def __init__(
        self,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: Optional[float] = None,
        *,
        system_prompt: str,
    ) -> None:
        self._system_prompt = system_prompt
        self._model = model or os.getenv("ANGY_OLLAMA_MODEL", "llama3")
        base_url = endpoint or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._endpoint = base_url.rstrip("/")
        timeout_override = os.getenv("ANGY_OLLAMA_TIMEOUT")
        if timeout is not None:
            self._timeout = timeout
        elif timeout_override:
            try:
                self._timeout = float(timeout_override)
            except ValueError:
                self._timeout = 60.0
        else:
            self._timeout = 60.0

        try:
            self._get("/api/tags")
        except RuntimeError as exc:  # pragma: no cover - depends on local server
            raise RuntimeError("Ollama server is not reachable") from exc

    def generate(self, instruction: str, session) -> str:  # session: IntakeSession protocol
        messages = [{"role": "system", "content": self._system_prompt}]
        for turn in session.conversation:
            role = "assistant" if turn.speaker.lower() == "angy" else "user"
            messages.append({"role": role, "content": turn.text})
        messages.append({"role": "user", "content": instruction})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }

        response = self._post("/api/chat", payload)
        message = response.get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("Ollama returned an empty response")
        return content.strip()

    # Internal helpers -----------------------------------------------------

    def _get(self, path: str) -> Dict[str, object]:
        url = f"{self._endpoint}{path}"
        request = urllib.request.Request(url=url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            raise RuntimeError(
                f"GET {url} timed out after {self._timeout} seconds."
            ) from exc
        except (urllib.error.URLError, ValueError) as exc:
            raise RuntimeError(f"Failed GET request to {url}") from exc

    def _post(self, path: str, payload: Dict[str, object]) -> Dict[str, object]:
        url = f"{self._endpoint}{path}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except socket.timeout as exc:
            raise RuntimeError(
                f"POST {url} timed out after {self._timeout} seconds."
            ) from exc
        except (urllib.error.URLError, ValueError) as exc:
            raise RuntimeError(f"Failed POST request to {url}") from exc

