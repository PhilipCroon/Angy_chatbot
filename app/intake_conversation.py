"""Reusable deterministic intake conversation logic for Angy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_questionnaire(filename: str) -> Dict[str, Any]:
    complaints_dir = Path(__file__).resolve().parent / "complaints"
    questionnaire_file = complaints_dir / filename
    with questionnaire_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError(f"Complaint file {filename} must contain a 'questions' list")
    return data


CHEST_PAIN_QUESTIONS = _load_questionnaire("chest_pain.json")
CV_RISK_QUESTIONS = _load_questionnaire("CV_risk.json")


@dataclass
class SectionState:
    key: str
    questions: List[Dict[str, str]]
    index: int = 0

    def current_question(self) -> Optional[Dict[str, str]]:
        if self.index >= len(self.questions):
            return None
        return self.questions[self.index]

    def advance(self) -> None:
        self.index += 1


class IntakeConversation:
    """Guides the scripted intake conversation and collects answers."""

    def __init__(self) -> None:
        self.stage = "ask_name"
        self.context: Dict[str, Optional[str]] = {
            "name": None,
            "dob": None,
            "reason": None,
            "additional_note": None,
        }
        self.sections_queue: List[str] = []
        self.section: Optional[SectionState] = None
        self.answers: Dict[str, Dict[str, Dict[str, str]]] = {"chest_pain": {}, "cv_risk": {}}

    def initial_prompt(self) -> str:
        return "Hello, welcome! May I have your full name?"

    def handle_message(self, message: str) -> str:
        message = (message or "").strip()
        if not message:
            return "Could you please repeat that?"

        if self.stage == "ask_name":
            self.context["name"] = message
            self.stage = "ask_dob"
            return f"Thank you {message}. Can you confirm your date of birth?"

        if self.stage == "ask_dob":
            self.context["dob"] = message
            self.stage = "ask_reason"
            return "Can you explain in your own words why you are referred to us?"

        if self.stage == "ask_reason":
            self.context["reason"] = message
            self._queue_sections(message)
            return self._finish_section()

        if self.stage == "summary":
            return self._build_summary()

        if self.stage == "await_additional":
            negative_responses = {"no", "nope", "nah", "nothing", "no thanks", "no thank you"}
            if message.lower() not in negative_responses:
                self.context["additional_note"] = message
            self.stage = "done"
            return "Thank you. I've captured that update."

        if self.stage == "done":
            return "We have completed the intake. Thank you!"

        section = self.section
        if section is None:
            return "Let me gather the remaining information from the clinical team."

        question = section.current_question()
        if question is None:
            return self._finish_section()

        self._record_answer(section.key, question, message)
        section.advance()
        return self._prepare_next_question()

    def export_state(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        answers_copy = {
            section: {
                key: {"prompt": value["prompt"], "answer": value["answer"]}
                for key, value in questions.items()
            }
            for section, questions in self.answers.items()
        }
        return {"context": dict(self.context), "answers": answers_copy}

    def _queue_sections(self, reason: str) -> None:
        self.sections_queue.extend(["chest_pain", "cv_risk"])

    def _start_section(self, key: str) -> str:
        questions = CHEST_PAIN_QUESTIONS["questions"] if key == "chest_pain" else CV_RISK_QUESTIONS["questions"]
        intro = (
            "Thank you. I’ll ask a few more questions about the chest pain."
            if key == "chest_pain"
            else "I’d also like to ask a few questions about cardiovascular risk factors."
        )
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
        self.stage = f"{section.key}_await"
        return question["prompt"]

    def _finish_section(self) -> str:
        self.section = None
        if not self.sections_queue:
            self.stage = "summary"
            return self._build_summary()
        next_key = self.sections_queue.pop(0)
        return self._start_section(next_key)

    def _record_answer(self, section_key: str, question: Dict[str, str], answer: str) -> None:
        cleaned = (answer or "").strip()
        if not cleaned:
            return
        section_answers = self.answers.setdefault(section_key, {})
        section_answers[question["key"]] = {"prompt": question["prompt"], "answer": cleaned}

    def _build_summary(self) -> str:
        lines: List[str] = []
        if self.context.get("name"):
            lines.append(f"Name: {self.context['name']}")
        if self.context.get("dob"):
            lines.append(f"Date of Birth: {self.context['dob']}")
        if self.context.get("reason"):
            lines.append(f"Chief Complaint: {self.context['reason']}")
        if self.answers.get("chest_pain"):
            lines.append("\nChest Pain Intake:")
            for key, value in self.answers["chest_pain"].items():
                lines.append(f"- {key}: {value['answer']}")
        if self.answers.get("cv_risk"):
            lines.append("\nCardiovascular Risk Factors:")
            for key, value in self.answers["cv_risk"].items():
                lines.append(f"- {key}: {value['answer']}")
        summary = "\n".join(lines) if lines else "Thank you. I have noted your information."
        summary += "\n\nIs there anything you'd like to add?"
        self.stage = "await_additional"
        return summary
