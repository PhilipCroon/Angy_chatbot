"""LangChain-backed clients and prompt helpers for the Angy chatbot."""

from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

try:
    from langchain_community.chat_models import ChatOllama
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    from langchain_core.prompts import ChatPromptTemplate
except ImportError:  # pragma: no cover - optional dependency
    ChatOllama = None  # type: ignore
    AIMessage = HumanMessage = SystemMessage = None  # type: ignore
    ChatPromptTemplate = None  # type: ignore

if TYPE_CHECKING:  # pragma: no cover - only for type hints
    from Angy_chatbot.app.chat_flow import IntakeSession


class LangChainChatLLM:
    """LangChain-powered wrapper around a locally hosted Ollama chat model."""

    def __init__(
        self,
        *,
        system_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> None:
        if ChatOllama is None or HumanMessage is None or SystemMessage is None:
            raise RuntimeError("langchain package is not installed")

        selected_model = model or os.getenv("ANGY_OLLAMA_MODEL", "llama3")
        self._system_message = SystemMessage(content=system_prompt)
        self._llm = ChatOllama(model=selected_model, temperature=temperature)

    # Public API -----------------------------------------------------------

    def generate(self, instruction: str, session: "IntakeSession") -> str:
        messages = self._build_history(session)
        messages.append(HumanMessage(content=instruction))
        return self._invoke(messages)

    def invoke_messages(
        self,
        session: "IntakeSession",
        new_messages: List[Any],
    ) -> str:
        messages = self._build_history(session)
        messages.extend(new_messages)
        return self._invoke(messages)

    # Internal helpers -----------------------------------------------------

    def _build_history(self, session: "IntakeSession") -> List[Any]:
        messages: List[Any] = [self._system_message]
        for turn in session.conversation:
            if turn.speaker.lower() == "angy":
                messages.append(AIMessage(content=turn.text))
            else:
                messages.append(HumanMessage(content=turn.text))
        return messages

    def _invoke(self, messages: List[Any]) -> str:
        response = self._llm.invoke(messages)
        content = getattr(response, "content", None)
        if isinstance(content, list):
            text_parts = [part.get("text") for part in content if isinstance(part, dict)]
            content = " ".join(filter(None, text_parts))
        if not content:
            content = str(response)
        return content.strip()


class LangChainFlowPrompter:
    """LangChain templates for higher-level conversation steps."""

    def __init__(self, llm: LangChainChatLLM) -> None:
        if ChatPromptTemplate is None:
            raise RuntimeError("LangChain prompts unavailable")
        self._llm = llm

        self._intro_ask_template = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "Introduce yourself as Angy, the virtual intake assistant. "
                    "Briefly explain your role and end by asking exactly: "
                    "'Could you please tell me your full name?'"
                )
            ]
        )
        self._intro_ack_template = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "Greet the patient by name ({patient_name}) as Angy and let "
                    "them know you already have their name on file. Invite them "
                    "to continue without asking any further questions in this turn."
                )
            ]
        )

        self._complaint_template = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "Thank the patient by name ({patient_name}) for sharing their "
                    "details. Ask exactly this question without additional context: "
                    "'Can you explain in your own words why you are referred to us?'"
                )
            ]
        )

        self._checklist_template = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "You are Angy, a warm and concise medical intake assistant. "
                    "Briefly acknowledge the patient's last statement in second person "
                    "(no more than 12 words) and then ask the following question "
                    "verbatim, ending with a question mark: "
                    "{question_prompt}. Patient name: {patient_name}. "
                    "Last patient statement: {last_statement}."
                )
            ]
        )

        self._summary_template = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "Provide a single concise recap sentence addressing the patient as "
                    "{patient_name}. Summarize the following key details already "
                    "collected: {fragments}. Keep it under 40 words."
                )
            ]
        )

        self._slug_router_template = ChatPromptTemplate.from_messages(
            [
                (
                    "human",
                    "You will be given a patient's statement and a list of available "
                    "intake checklists. Respond ONLY with the slug that best matches "
                    "the patient's needs or NONE if nothing fits.\n\n"
                    "Patient statement: {statement}\n"
                    "Available checklists:\n{catalog}\n"
                )
            ]
        )

    # Prompt helpers ------------------------------------------------------

    def intro_prompt(self, session: "IntakeSession", needs_name: bool) -> str:
        if needs_name:
            messages = self._intro_ask_template.format_messages()
        else:
            patient_name = session.patient_name or "there"
            messages = self._intro_ack_template.format_messages(
                patient_name=patient_name
            )
        return self._llm.invoke_messages(session, messages)

    def complaint_prompt(self, session: "IntakeSession") -> str:
        patient_name = session.patient_name or "there"
        messages = self._complaint_template.format_messages(patient_name=patient_name)
        return self._llm.invoke_messages(session, messages)

    def classify_slug(self, session: "IntakeSession", statement: str, catalog: List[str]) -> Optional[str]:
        catalog_text = "\n".join(catalog)
        messages = self._slug_router_template.format_messages(
            statement=statement,
            catalog=catalog_text,
        )
        response = self._llm.invoke_messages(session, messages)
        candidate = response.strip().splitlines()[0].strip().lower()
        candidate = candidate.strip("`""' ")
        candidate = candidate.split()[0] if candidate else ""
        if candidate == "none":
            return None
        return candidate

    def checklist_prompt(
        self,
        session: "IntakeSession",
        question_prompt: str,
        last_statement: Optional[str],
    ) -> str:
        patient_name = session.patient_name or "there"
        messages = self._checklist_template.format_messages(
            patient_name=patient_name,
            question_prompt=question_prompt,
            last_statement=last_statement or "",
        )
        return self._llm.invoke_messages(session, messages)

    def checklist_summary(
        self,
        session: "IntakeSession",
        fragments: str,
    ) -> str:
        patient_name = session.patient_name or "there"
        messages = self._summary_template.format_messages(
            patient_name=patient_name,
            fragments=fragments,
        )
        return self._llm.invoke_messages(session, messages)

