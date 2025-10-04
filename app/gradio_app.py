"""Gradio interface for the Angy intake flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional

import gradio as gr

# Ensure project root on sys.path when run as a script
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Angy_chatbot.app.chat_flow import (
    SYSTEM_PROMPT,
    CHEST_PAIN_QUESTIONS,
    CV_RISK_QUESTIONS,
    POSITIVE_CONFIRMATIONS,
    _infer_answer,
    _natural_confirmation,
    is_confirmation,
)
from Angy_chatbot.app.llm.langchain_client import LangchainIntakeClient

NEGATIVE_RESPONSES = {"no", "nope", "nah"}


@dataclass
class SectionState:
    key: str
    questions: List[Dict[str, str]]
    index: int = 0
    pending_inferred: Optional[str] = None

    def current_question(self) -> Optional[Dict[str, str]]:
        if self.index >= len(self.questions):
            return None
        return self.questions[self.index]

    def advance(self) -> None:
        self.index += 1
        self.pending_inferred = None

    def finished(self) -> bool:
        return self.index >= len(self.questions)
    

class IntakeConversation:
    """Conversation manager shared by CLI and Gradio front-ends."""

    def __init__(self) -> None:
        # self.client = LangchainIntakeClient(
        #     system_prompt=SYSTEM_PROMPT,
        #     model=model,
        #     provider=provider or "ollama",
        #     openai_api_key=api_key,
        # )
        
        self.client = LangchainIntakeClient(
            system_prompt="You are a helpful assistant.",
            model="gpt-4o-mini",
            provider="openai",
            openai_api_key="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",
        )
        self.stage = "ask_name"
        self.context: Dict[str, Optional[str]] = {"name": None, "dob": None, "reason": None}
        self.sections_queue: List[str] = []
        self.section: Optional[SectionState] = None
        self.answers: Dict[str, Dict[str, str]] = {"chest_pain": {}, "cv_risk": {}}

    # ------------------------------------------------------------------
    def initial_prompt(self) -> str:
        prompt = "Hello, welcome! May I have your full name?"
        self.client.add_assistant_message(prompt)
        return prompt

    def _record_answer(self, section_key: str, question_key: str, answer: str) -> None:
        self.answers.setdefault(section_key, {})[question_key] = answer.strip()

    def _queue_sections(self, reason: str) -> None:
        reason_lower = reason.lower()
        if "chest pain" in reason_lower:
            self.sections_queue.append("chest_pain")
        if any(keyword in reason_lower for keyword in ("risk", "cardio")):
            self.sections_queue.append("cv_risk")
        if not self.sections_queue:
            self.sections_queue.append("chest_pain")

    def _start_section(self, key: str) -> str:
        questions = CHEST_PAIN_QUESTIONS["questions"] if key == "chest_pain" else CV_RISK_QUESTIONS["questions"]
        intro = (
            "Thank you. I’ll ask a few more questions about the chest pain."
            if key == "chest_pain"
            else "I’d also like to ask a few questions about cardiovascular risk factors."
        )
        self.client.add_assistant_message(intro)
        self.section = SectionState(key=key, questions=questions)
        prompt = self._prepare_next_question()
        return intro + "\n" + prompt

    def _prepare_next_question(self) -> str:
        section = self.section
        if section is None:
            return self._build_summary()
        question = section.current_question()
        if question is None:
            return self._finish_section()

        inferred = _infer_answer(
            self.client,
            question["prompt"],
            expected_type=question.get("answer_type"),
            stream=False,
        )
        if inferred:
            section.pending_inferred = inferred
            confirmation = _natural_confirmation(self.client, question["prompt"], inferred)
            self.client.add_assistant_message(confirmation)
            self.stage = f"{section.key}_confirm"
            return confirmation

        prompt = question["prompt"]
        self.client.add_assistant_message(prompt)
        self.stage = f"{section.key}_await"
        return prompt

    def _finish_section(self) -> str:
        self.section = None
        if not self.sections_queue:
            self.stage = "summary"
            return self._build_summary()
        next_key = self.sections_queue.pop(0)
        return self._start_section(next_key)

    def _build_summary(self) -> str:
        lines = []
        if self.context.get("name"):
            lines.append(f"Name: {self.context['name']}")
        if self.context.get("dob"):
            lines.append(f"Date of Birth: {self.context['dob']}")
        if self.context.get("reason"):
            lines.append(f"Chief Complaint: {self.context['reason']}")
        if self.answers["chest_pain"]:
            lines.append("\nChest Pain Intake:")
            for key, value in self.answers["chest_pain"].items():
                lines.append(f"- {key}: {value}")
        if self.answers["cv_risk"]:
            lines.append("\nCardiovascular Risk Factors:")
            for key, value in self.answers["cv_risk"].items():
                lines.append(f"- {key}: {value}")
        summary = "\n".join(lines) if lines else "Thank you. I have noted your information."
        self.client.add_assistant_message(summary)
        self.stage = "done"
        return summary

    def handle_message(self, message: str) -> str:
        message = message.strip()
        if not message:
            return "Could you please repeat that?"

        self.client.add_patient_message(message)
        

        if self.stage == "ask_name":
            self.context["name"] = message
            prompt = f"Thank you {message}. Can you confirm your date of birth?"
            self.client.add_assistant_message(prompt)
            self.stage = "ask_dob"
            return prompt

        if self.stage == "ask_dob":
            self.context["dob"] = message
            prompt = "Can you explain in your own words why you are referred to us?"
            self.client.add_assistant_message(prompt)
            self.stage = "ask_reason"
            return prompt

        if self.stage == "ask_reason":
            self.context["reason"] = message
            self._queue_sections(message)
            return self._finish_section()

        if self.stage == "summary":
            return self._build_summary()

        if self.stage == "done":
            return "We have completed the intake. Thank you!"

        section = self.section
        if section is None:
            return "Let me gather the remaining information from the clinical team."

        question = section.current_question()
        if question is None:
            return self._finish_section()

        if self.stage == f"{section.key}_confirm":
            if is_confirmation(self.client, message):
                self.client.add_structured_patient_message(question["prompt"], section.pending_inferred or "", add_raw=False)
                self.answers[section.key][question["key"]] = section.pending_inferred or ""
                section.advance()
                return self._prepare_next_question()
            if message.lower() in POSITIVE_CONFIRMATIONS or message.lower().startswith("yes"):
                self.client.add_structured_patient_message(question["prompt"], section.pending_inferred or "", add_raw=False)
                self.answers[section.key][question["key"]] = section.pending_inferred or ""
                section.advance()
                return self._prepare_next_question()
            if message.lower() in NEGATIVE_RESPONSES:
                self.stage = f"{section.key}_await"
                prompt = question["prompt"]
                self.client.add_assistant_message(prompt)
                return prompt
            self.client.add_structured_patient_message(question["prompt"], message, add_raw=False)
            self.answers[section.key][question["key"]] = message
            section.advance()
            return self._prepare_next_question()

        if self.stage == f"{section.key}_await":
            self.client.add_structured_patient_message(question["prompt"], message, add_raw=False)
            self.answers[section.key][question["key"]] = message
            section.advance()
            return self._prepare_next_question()

        return "Thank you. Let's continue."


if __name__ == "__main__":
    conv = IntakeConversation()

    def respond(message, history):
        """This function connects Gradio’s chat UI to your IntakeConversation logic."""
        reply = conv.handle_message(message)
        return reply

    # Start with the system's first prompt
    start_message = conv.initial_prompt()

    # Use Gradio's ChatInterface (newer and simpler)
    gr.ChatInterface(
        fn=respond,
        title="Angy Clinical Intake Assistant",
        description="A professional and warm assistant guiding patients through medical intake.",
        theme="soft",
        examples=None,
        chatbot=gr.Chatbot(height=400),
    ).launch()
