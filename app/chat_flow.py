from langchain_core.chat_history import InMemoryChatMessageHistory
import json
import re
from pathlib import Path
from typing import Iterable, Optional

from langchain_core.messages import HumanMessage

from llm import LangchainIntakeClient

SYSTEM_PROMPT = (
    "You are Angy, a professional and warm virtual assistant for medical intake. "
    "You greet the patient, collect their basic info, then guide them through intake questions. "
    "You avoid making diagnoses and never mention being AI."
)


def _load_chest_pain_questions() -> dict:
    complaints_dir = Path(__file__).resolve().parent / "complaints"
    chest_pain_file = complaints_dir / "chest_pain.json"
    if not chest_pain_file.exists():
        raise FileNotFoundError(f"Expected complaint file not found: {chest_pain_file}")

    with chest_pain_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or "questions" not in data:
        raise ValueError("Chest pain complaint file must contain a 'questions' list")
    return data


CHEST_PAIN_QUESTIONS = _load_chest_pain_questions()


def get_answered_keys(history: Iterable[HumanMessage]) -> set[str]:
    """Extract question keys already answered."""
    answered = set()
    for msg in history:
        if isinstance(msg, HumanMessage):
            for q in CHEST_PAIN_QUESTIONS["questions"]:
                if q["prompt"] in msg.content:
                    answered.add(q["key"])
    return answered


def _strip_question_prefix(text: str) -> str:
    for q in CHEST_PAIN_QUESTIONS["questions"]:
        prompt = q["prompt"].strip()
        if text.startswith(prompt):
            remainder = text[len(prompt):].strip()
            if remainder:
                return remainder
    return text.strip()


# Helper sanitizer for inferred answers
def _sanitize_inferred(text: str) -> Optional[str]:
    """Return a short, useful inferred answer or None if the model reply looks like a greeting/verbose prompt.

    Heuristic:
    - Remove leading/trailing whitespace
    - If reply starts with a conversational greeting/boilerplate, return None
    - Otherwise return the first sentence or the first non-empty line
    """
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    lower = cleaned.lower()
    # common undesired starters that indicate the model is trying to re-open the conversation
    for starter in ("hello", "hi", "good", "thank", "please", "dear"):
        if lower.startswith(starter):
            return None
    # prefer first meaningful line
    for sep in ("\n", ". "):
        parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
        if parts:
            return parts[0]
    return cleaned


session_store = {}

def get_by_session_id(session_id: str) -> InMemoryChatMessageHistory:
    if session_id not in session_store:
        session_store[session_id] = InMemoryChatMessageHistory()
    return session_store[session_id]

def format_history(messages):
    result = []
    for m in messages:
        role = m.type if hasattr(m, "type") else m.__class__.__name__.replace("Message", "").lower()
        result.append(f"{role.title()}: {m.content}")
    return "\n".join(result)


POSITIVE_CONFIRMATIONS = {
    "yes",
    "y",
    "yeah",
    "correct",
    "that's right",
    "thats right",
    "right",
    "yep",
    "affirmative",
    "sure",
}


def _infer_answer(
    client: LangchainIntakeClient,
    prompt: str,
    *,
    stream: bool = False,
) -> Optional[str]:
    context_entries = client.similar_messages(prompt, top_k=5, min_score=0.5)
    print("\n[DEBUG] Retrieval context for prompt:")
    for entry in context_entries:
        print(f"  - ({entry['role']}) {entry['text']}")

    # if not context_entries:
    #     return None
    context_text = "\n".join(
        f"- {msg.content}" for msg in client.history()
        if hasattr(msg, "content") and msg.content
    )

    # context_text = "\n".join(f"- {entry['text']}" for entry in client.history)
    instruction = (
        "You are a clinical intake assistant extracting answers from previous patient statements.\n"
        f"Question: {prompt}\n"
        "Patient statements:\n"
        f"{context_text}\n"
        "If the question has already been answered, reply exactly with 'ANSWER: <short answer>'.\n"
        "If it is not answered, reply exactly with 'UNKNOWN'."
    )

    print("[DEBUG] Instruction to model:")
    print(instruction)
    response = client.ask(instruction, history=[], stream=stream).strip()
    print("[DEBUG] Model response:")
    print(response)
    lowered = response.lower()
    if lowered.startswith("answer:"):
        candidate = response.split(":", 1)[1].strip()
        return _sanitize_inferred(candidate) or candidate

    return None


def ask_basic_info(client: LangchainIntakeClient) -> dict:
    name = input("Angy: Hello, welcome! May I have your full name?\nYou: ")
    client.add_patient_message(name)

    dob = input("Angy: Thank you! Can you confirm your date of birth?\nYou: ")
    client.add_patient_message(dob)

    complaint = input("Angy: What brings you in today?\nYou: ")
    client.add_patient_message(complaint)

    return {"name": name, "dob": dob, "chief_complaint": complaint}


def is_confirmation(client: LangchainIntakeClient, reply: str) -> bool:
    """Ask the LLM if the reply confirms the suggested answer."""
    instruction = (
        "You are a clinical intake assistant. "
        "Given a patient reply, determine if it is confirming an answer. "
        "Reply strictly with 'YES' if it confirms, or 'NO' otherwise.\n\n"
        f"Patient reply: {reply}"
    )
    response = client.ask(instruction, history=[], stream=False).strip().lower()
    return response.startswith("yes")


def handle_chest_pain(client: LangchainIntakeClient):
    print("Angy: Thank you. I’ll ask a few more questions about the chest pain.\n")

    answered_keys = get_answered_keys(client.history())

    for q in CHEST_PAIN_QUESTIONS["questions"]:
        if q["key"] in answered_keys:
            continue

        inferred = _infer_answer(client, q["prompt"], stream=True)
        if inferred:
            confirmation = f"It sounds like {inferred}. Is that correct?"
            print(f"Angy: {confirmation}")
            client.add_assistant_message(confirmation)
            patient_reply = input("You: ").strip()
            client.add_patient_message(patient_reply)

            if is_confirmation(client, patient_reply):
                client.add_structured_patient_message(q["prompt"], inferred)
                answered_keys.add(q["key"])
                print("Confirmed skipping")
                continue


        follow_up = q["prompt"]
        print(f"Angy: {follow_up}")
        client.add_assistant_message(follow_up)
        answer = input("You: ").strip()
        client.add_structured_patient_message(q["prompt"], answer)
        answered_keys.add(q["key"])


def intake_flow():
    print("== Angy ChatBot (Chest Pain Intake) ==\n")

    # client = LangchainIntakeClient(system_prompt=SYSTEM_PROMPT, model="phi3", temperature=0.2)
    client = LangchainIntakeClient(
    system_prompt="You are a helpful assistant.",
    model="gpt-4o-mini",
    provider="openai",
    openai_api_key="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",
)

    basic_info = ask_basic_info(client)

    if "chest pain" in basic_info["chief_complaint"].lower():
        handle_chest_pain(client)

    chest_pain_answers = {
        q["key"]: next(
            (
                msg.content.replace(q["prompt"], "").strip()
                for msg in client.patient_messages()
                if msg.content.startswith(q["prompt"])
            ),
            None
        )
        for q in CHEST_PAIN_QUESTIONS["questions"]
    }

    print("\n== Intake Complete ==")
    print("Angy: Thank you. I’ve noted everything and will pass it on to your clinical team.")

    return {
        "name": basic_info["name"],
        "dob": basic_info["dob"],
        "chief_complaint": basic_info["chief_complaint"],
        "chest_pain_answers": chest_pain_answers
    }


if __name__ == "__main__":
    intake_summary = intake_flow()
    print("\n== Summary ==")
    print(json.dumps(intake_summary, indent=2))
