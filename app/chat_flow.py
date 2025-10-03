"""Core chat flow for the Angy intake chatbot MVP.

This module provides a minimal interactive chatbot that introduces
itself as Angy, confirms the patient's name and date of birth, and
collects a short chief complaint summary. It is structured so that the
response generation can be backed by a large language model when one is
available, with a lightweight template-based fallback for offline use.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

try:  # Optional import – only used when the OpenAI client is available.
    from openai import OpenAI
except ImportError:  # pragma: no cover - fallback when openai isn't installed.
    OpenAI = None  # type: ignore


SYSTEM_PROMPT = (
    "You are Angy, a warm and professional virtual medical assistant who "
    "guides adult patients through an intake focused on chest pain. "
    "You greet patients, verify their information, and gather the chief "
    "complaint details needed for the clinical team. Keep your tone calm, "
    "empathetic, and concise. Avoid making diagnoses or promises about "
    "treatment, and do not mention you are an AI or language model."
)


@dataclass
class ConversationTurn:
    speaker: str
    text: str


@dataclass
class IntakeSession:
    patient_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    chief_complaint: Optional[str] = None
    conversation: List[ConversationTurn] = field(default_factory=list)

    def add_turn(self, speaker: str, text: str) -> None:
        self.conversation.append(ConversationTurn(speaker=speaker, text=text))


class LLMClient(Protocol):
    """Protocol describing the response generation interface."""

    def generate(self, instruction: str, session: IntakeSession) -> str:
        ...


class OpenAIChatLLM:
    """Wrapper around the OpenAI chat completion API."""

    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.2, max_tokens: int = 300) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY environment variable is not set")

        self._client = OpenAI()
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def generate(self, instruction: str, session: IntakeSession) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in session.conversation:
            role = "assistant" if turn.speaker.lower() == "angy" else "user"
            messages.append({"role": role, "content": turn.text})
        messages.append({"role": "user", "content": instruction})

        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content.strip()


class OllamaChatLLM:
    """Wrapper around a locally hosted Ollama chat model."""

    def __init__(
        self,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self._model = model or os.getenv("ANGY_OLLAMA_MODEL", "llama3")
        base_url = endpoint or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._endpoint = base_url.rstrip("/")
        self._timeout = timeout

        try:
            self._get("/api/tags")
        except RuntimeError as exc:  # pragma: no cover - depends on local server
            raise RuntimeError("Ollama server is not reachable") from exc

    def generate(self, instruction: str, session: IntakeSession) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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

    def _get(self, path: str) -> dict:
        url = f"{self._endpoint}{path}"
        request = urllib.request.Request(url=url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError) as exc:
            raise RuntimeError(f"Failed GET request to {url}") from exc

    def _post(self, path: str, payload: dict) -> dict:
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
        except (urllib.error.URLError, ValueError) as exc:
            raise RuntimeError(f"Failed POST request to {url}") from exc


class TemplateLLM:
    """Fallback response generator for environments without LLM access."""

    def generate(self, instruction: str, session: IntakeSession) -> str:
        lower_instruction = instruction.lower()
        name = session.patient_name or "there"
        dob = session.date_of_birth or "your date of birth"
        complaint = session.chief_complaint or "what brings you in"

        if "introduce" in lower_instruction:
            return (
                "Hi, I'm Angy, the virtual assistant for your care team. I'm here "
                "to help gather some details so your clinician has everything they "
                "need. Let's start by making sure I have the right chart — may I "
                "have your full name?"
            )

        if "confirm both the name" in lower_instruction:
            return (
                f"Perfect, thanks {name}. I have you down with the date of birth "
                f"{dob}. I'd love to hear, in your own words, what brings you in "
                "today."
            )

        if "date of birth" in lower_instruction:
            return (
                f"Thanks, {name}. To make sure I stay in the right chart, could you "
                "confirm your date of birth for me?"
            )

        if "acknowledge their summary" in lower_instruction:
            return (
                f"I appreciate you sharing that {name}. I'll note that you're here "
                f"because of {complaint}. A clinician will be with you shortly to "
                "go over the details together."
            )

        # Generic polite fallback.
        return (
            "Thanks for letting me know. I'll make sure the care team has this "
            "information before they join us."
        )


def build_default_llm() -> LLMClient:
    for factory in (OllamaChatLLM, OpenAIChatLLM):
        try:
            return factory()
        except Exception:
            continue
    return TemplateLLM()


class AngyChatFlow:
    """Conversation orchestrator for the Angy intake experience."""

    def __init__(self, llm: Optional[LLMClient] = None) -> None:
        self.session = IntakeSession()
        self.llm = llm or build_default_llm()

    def _agent_reply(self, instruction: str) -> str:
        reply = self.llm.generate(instruction, self.session)
        self.session.add_turn("Angy", reply)
        return reply

    def _record_patient(self, utterance: str) -> None:
        self.session.add_turn("Patient", utterance)

    def run_cli(self) -> IntakeSession:
        """Run a simple command-line chat session."""

        # Step 1: Intro & name verification.
        introduction = self._agent_reply(
            "Introduce yourself as Angy, explain that you're assisting with the "
            "intake, and ask for the patient's full name."
        )
        print(f"Angy: {introduction}\n")

        patient_name = input("Patient: ").strip()
        self.session.patient_name = patient_name
        self._record_patient(patient_name)

        # Step 2: Date of birth.
        dob_prompt = self._agent_reply(
            "Acknowledge their name and ask them to confirm their date of birth "
            "in a friendly, professional tone."
        )
        print(f"\nAngy: {dob_prompt}\n")

        patient_dob = input("Patient: ").strip()
        self.session.date_of_birth = patient_dob
        self._record_patient(patient_dob)

        # Step 3: Chief complaint.
        complaint_prompt = self._agent_reply(
            "Thank them, confirm both the name and the date of birth you heard, "
            "then invite them to briefly describe what brings them in today."
        )
        print(f"\nAngy: {complaint_prompt}\n")

        patient_complaint = input("Patient: ").strip()
        self.session.chief_complaint = patient_complaint
        self._record_patient(patient_complaint)

        # Step 4: Warm acknowledgement.
        wrap_up = self._agent_reply(
            "Acknowledge their summary without offering medical advice or "
            "diagnoses. Let them know you'll pass the information to the clinical "
            "team and close in a warm tone."
        )
        print(f"\nAngy: {wrap_up}\n")

        return self.session


if __name__ == "__main__":
    bot = AngyChatFlow()
    session = bot.run_cli()

    print("\n--- Intake Summary ---")
    print(f"Name: {session.patient_name}")
    print(f"Date of Birth: {session.date_of_birth}")
    print(f"Chief Complaint: {session.chief_complaint}")
