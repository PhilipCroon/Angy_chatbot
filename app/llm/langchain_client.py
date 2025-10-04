"""LangChain client wrapper used by the Angy intake chatbot."""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from langchain_community.chat_models import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain.memory import ConversationBufferMemory

try:  # Optional embedding support
    from langchain_community.embeddings import HuggingFaceEmbeddings
except ImportError:  # pragma: no cover - embeddings optional
    HuggingFaceEmbeddings = None  # type: ignore


class LangchainIntakeClient:
    """Small helper around LangChain primitives with chat memory and embeddings."""

    def __init__(
        self,
        *,
        system_prompt: str,
        model: str = "phi3",
        temperature: float = 0.2,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self._system_prompt = system_prompt
        self._llm = ChatOllama(model=model, temperature=temperature)
        self._memory = ConversationBufferMemory(return_messages=True)
        self._embeddings: List[Dict[str, object]] = []

        if HuggingFaceEmbeddings is not None:
            try:
                self._embedder = HuggingFaceEmbeddings(model_name=embedding_model)
            except Exception:  # pragma: no cover
                self._embedder = None
        else:
            self._embedder = None

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------
    def add_patient_message(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._memory.chat_memory.add_user_message(cleaned)
        self._store_embedding(role="patient", text=cleaned)

    def add_assistant_message(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._memory.chat_memory.add_ai_message(cleaned)
        self._store_embedding(role="assistant", text=cleaned)

    def add_structured_patient_message(self, prompt: str, answer: str) -> None:
        answer_clean = answer.strip()
        if not answer_clean:
            return
        self.add_patient_message(answer_clean)  # raw answer for retrieval
        structured = f"{prompt} {answer_clean}".strip()
        if structured != answer_clean:
            self._memory.chat_memory.add_user_message(structured)
            self._store_embedding(role="patient_structured", text=structured)

    def history(self) -> List[BaseMessage]:
        return list(self._memory.chat_memory.messages)

    def patient_messages(self) -> List[HumanMessage]:
        return [
            msg
            for msg in self._memory.chat_memory.messages
            if isinstance(msg, HumanMessage)
        ]

    # ------------------------------------------------------------------
    # LLM invocation
    # ------------------------------------------------------------------
    def ask(
        self,
        prompt: str,
        history: Optional[Iterable[BaseMessage]] = None,
        *,
        stream: bool = False,
    ) -> str:
        messages: List[BaseMessage] = [SystemMessage(content=self._system_prompt)]
        if history is None:
            messages.extend(self.history())
        else:
            messages.extend(list(history))
        messages.append(HumanMessage(content=prompt))

        if stream:
            fragments: List[str] = []
            for chunk in self._llm.stream(messages):
                piece = getattr(chunk, "content", "")
                if isinstance(piece, list):
                    piece = "".join(
                        part.get("text", "") for part in piece if isinstance(part, dict)
                    )
                if piece:
                    print(piece, end="|", flush=True)
                    fragments.append(piece)
            if fragments:
                print()
            return "".join(fragments).strip()

        response = self._llm.invoke(messages)
        content = getattr(response, "content", None)
        if isinstance(content, list):
            text_parts = [part.get("text") for part in content if isinstance(part, dict)]
            content = " ".join(filter(None, text_parts))
        if not content:
            content = str(response)
        return content.strip()

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------
    def embed_query(self, text: str) -> Optional[List[float]]:
        if self._embedder is None:
            return None
        try:
            return self._embedder.embed_query(text)
        except Exception:  # pragma: no cover
            return None

    def vector_store(self) -> List[Dict[str, object]]:
        return list(self._embeddings)

    def similar_messages(
        self,
        prompt: str,
        *,
        top_k: int = 3,
        min_score: float = 0.5,
    ) -> List[Dict[str, object]]:
        query_vec = self.embed_query(prompt)
        if not query_vec:
            return []

        scored: List[Tuple[float, Dict[str, object]]] = []
        for entry in self._embeddings:
            vector = entry.get("vector")
            if not vector:
                continue
            score = _cosine_similarity(query_vec, vector)
            if score >= min_score:
                scored.append((score, entry))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def _store_embedding(self, *, role: str, text: str) -> None:
        if not text:
            return
        if self._embedder is None:
            self._embeddings.append({"role": role, "text": text, "vector": None})
            return
        try:
            vector = self._embedder.embed_query(text)
        except Exception:  # pragma: no cover
            vector = None
        self._embeddings.append({"role": role, "text": text, "vector": vector})


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
