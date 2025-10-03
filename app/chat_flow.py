from pathlib import Path
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_community.chat_models import ChatOllama
from langchain.memory import ConversationBufferMemory
import json


# === Setup LangChain components ===
SYSTEM_PROMPT = (
    "You are Angy, a professional and warm virtual assistant for medical intake. "
    "You greet the patient, collect their basic info, then guide them through intake questions. "
    "You avoid making diagnoses and never mention being AI."
)

llm = ChatOllama(model="phi3", temperature=0.2)
memory = ConversationBufferMemory(return_messages=True)


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

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{input}")
])


def ask_question(question, history):
    """Query LLM with structured message history and the current question."""
    # Build messages: system message, previous conversation history, then the current human question
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    # history is expected to be a list of LangChain Message objects (HumanMessage / AIMessage)
    if history:
        messages.extend(list(history))
    messages.append(HumanMessage(content=question))

    # Invoke the model with the composed messages
    result = llm.invoke(messages)
    return result



def get_answered_keys(history: list[str]) -> set[str]:
    """Extract question keys already answered."""
    answered = set()
    for msg in history:
        if isinstance(msg, HumanMessage):
            for q in CHEST_PAIN_QUESTIONS["questions"]:
                if q["prompt"] in msg.content:
                    answered.add(q["key"])
    return answered


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


def intake_flow():
    print("== Angy ChatBot (Chest Pain Intake) ==\n")

    # --- Name ---
    name = input("Angy: Hello, welcome! May I have your full name?\nYou: ")
    memory.chat_memory.add_user_message(name)

    # --- Date of Birth ---
    dob = input("Angy: Thank you! Can you confirm your date of birth?\nYou: ")
    memory.chat_memory.add_user_message(dob)

    # --- Chief Complaint ---
    complaint = input("Angy: What brings you in today?\nYou: ")
    memory.chat_memory.add_user_message(complaint)

    if "chest pain" in complaint.lower():
        print("Angy: Thank you. I’ll ask a few more questions about the chest pain.\n")

        # Use the stored chat memory messages as the conversation history
        history = list(memory.chat_memory.messages)
        # Do NOT clear memory here — keep the conversation for LLM context
        answered_keys = get_answered_keys(history)

        for q in CHEST_PAIN_QUESTIONS["questions"]:
            if q["key"] not in answered_keys:
                # Ask the LLM to infer an answer from the existing history
                result = ask_question(q["prompt"], history)
                raw = getattr(result, "content", str(result)).strip()
                inferred = _sanitize_inferred(raw)
                if inferred:
                    # Show what was inferred and store it as if the patient answered
                    print(f"Angy (inferred): {inferred}")
                    memory.chat_memory.add_user_message(f"{q['prompt']} {inferred}")
                    # also append to our local history so subsequent inferences see it
                    history.append(HumanMessage(content=f"{q['prompt']} {inferred}"))
                else:
                    # Fall back to asking the user directly
                    answer = input(f"Angy: {q['prompt']}\nYou: ")
                    memory.chat_memory.add_user_message(f"{q['prompt']} {answer}")
                    history.append(HumanMessage(content=f"{q['prompt']} {answer}"))

    print("\n== Intake Complete ==")
    print("Angy: Thank you. I’ve noted everything and will pass it on to your clinical team.")

    # Optional: return structured output
    return {
        "name": name,
        "dob": dob,
        "chief_complaint": complaint,
        "chest_pain_answers": {
            q["key"]: next(
                (msg.content.replace(q["prompt"], "").strip()
                 for msg in memory.chat_memory.messages
                 if isinstance(msg, HumanMessage) and msg.content.startswith(q["prompt"])),
                None
            )
            for q in CHEST_PAIN_QUESTIONS["questions"]
        }
    }


if __name__ == "__main__":
    intake_summary = intake_flow()
    print("\n== Summary ==")
    print(json.dumps(intake_summary, indent=2))