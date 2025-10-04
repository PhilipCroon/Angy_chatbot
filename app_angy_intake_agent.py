"""FastAPI backend for the Angy intake chatbot with direct FHIR generation."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Make the ``app`` folder importable (contains intake_conversation module)
sys.path.insert(0, str(Path(__file__).parent / "app"))
from intake_conversation import IntakeConversation


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Angy Chatbot with FHIR Integration",
    description="Guided medical intake conversation with automatic FHIR resource creation",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models & storage
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    fhir_resources: List[Dict[str, Any]] = []
    medplum_links: List[str] = []
    decomposed_count: Optional[int] = None


class SessionInfo(BaseModel):
    session_id: str
    patient_id: Optional[str]
    patient_name: Optional[str]
    created_at: str
    message_count: int
    fhir_resource_count: int
    resource_counts: Dict[str, int]


SESSIONS: Dict[str, "PatientSession"] = {}
MEDPLUM_TOKEN: Optional[str] = None

MEDICATION_KEYWORDS = [
    " mg",
    "mcg",
    "take ",
    "taking ",
    "tablet",
    "pill",
    "capsule",
    "beta blocker",
    "beta-blocker",
    "metformin",
    "lisinopril",
    "atorvastatin",
    "statin",
    "insulin",
    "aspirin",
    "metoprolol",
    "amlodipine",
    "clopidogrel",
    "warfarin",
    "anticoagulant",
]


# ---------------------------------------------------------------------------
# Utilities for FHIR resource generation
# ---------------------------------------------------------------------------

def normalize_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None

    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue

    # Try optional dateutil parsing if available
    try:  # pragma: no cover - optional dependency
        from dateutil import parser

        return parser.parse(text, fuzzy=True).date().isoformat()
    except Exception:
        return None


def split_name(full_name: Optional[str]) -> Tuple[List[str], Optional[str]]:
    if not full_name:
        return [], None
    tokens = [token for token in re.split(r"\s+", full_name.strip()) if token]
    if len(tokens) >= 2:
        return tokens[:-1], tokens[-1]
    return tokens, None if tokens else None


def make_patient_resource(context: Dict[str, Optional[str]], session_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    name = context.get("name")
    dob = normalize_date(context.get("dob"))

    if not name and not dob:
        return None, None

    patient_id = f"patient-{session_id}"
    resource: Dict[str, Any] = {"resourceType": "Patient", "id": patient_id}

    given_parts, family = split_name(name)
    if given_parts or family:
        name_dict: Dict[str, Any] = {}
        if given_parts:
            name_dict["given"] = given_parts
        if family:
            name_dict["family"] = family
        resource["name"] = [name_dict]

    if dob:
        resource["birthDate"] = dob

    display_name_parts = given_parts + ([family] if family else [])
    display_name = " ".join(display_name_parts) if display_name_parts else name

    return resource, display_name


def make_condition_resource(context: Dict[str, Optional[str]], patient_id: Optional[str], session_id: str) -> Optional[Dict[str, Any]]:
    reason = (context.get("reason") or "").strip()
    if not reason:
        return None

    resource: Dict[str, Any] = {
        "resourceType": "Condition",
        "id": f"condition-{session_id}",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                    "display": "Active",
                }
            ]
        },
        "code": {
            "text": reason,
        },
        "recordedDate": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }

    reason_lower = reason.lower()
    if "chest pain" in reason_lower:
        resource["code"]["coding"] = [
            {
                "system": "http://snomed.info/sct",
                "code": "29857009",
                "display": "Chest pain",
            }
        ]

    if patient_id:
        resource["subject"] = {"reference": f"Patient/{patient_id}"}

    resource.setdefault("note", []).append({"text": reason})
    return resource


def make_questionnaire_responses(
    answers: Dict[str, Dict[str, Dict[str, str]]],
    patient_id: Optional[str],
    session_id: str,
) -> List[Dict[str, Any]]:
    resources: List[Dict[str, Any]] = []
    for section_key, section_answers in answers.items():
        if not section_answers:
            continue
        items = []
        for key, value in section_answers.items():
            answer_text = value.get("answer")
            prompt = value.get("prompt")
            if not answer_text:
                continue
            items.append(
                {
                    "linkId": key,
                    "text": prompt,
                    "answer": [{"valueString": answer_text}],
                }
            )
        if not items:
            continue
        resource: Dict[str, Any] = {
            "resourceType": "QuestionnaireResponse",
            "id": f"qr-{section_key}-{session_id}",
            "status": "completed",
            "authored": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "item": items,
        }
        if patient_id:
            resource["subject"] = {"reference": f"Patient/{patient_id}"}
        if section_key == "chest_pain":
            resource["questionnaire"] = "Questionnaire/chest-pain-intake"
        elif section_key == "cv_risk":
            resource["questionnaire"] = "Questionnaire/cv-risk"
        resources.append(resource)
    return resources


def looks_like_medication(text: str) -> bool:
    lowered = text.lower()
    if "no medication" in lowered or "no meds" in lowered:
        return False
    if re.search(r"\b\d+\s*mg\b", lowered):
        return True
    return any(keyword in lowered for keyword in MEDICATION_KEYWORDS)


def hash_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.strip().lower().encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def make_medication_statements(
    answers: Dict[str, Dict[str, Dict[str, str]]],
    history: List[Dict[str, Optional[str]]],
    patient_id: Optional[str],
) -> List[Dict[str, Any]]:
    texts: List[str] = []
    for section in answers.values():
        for value in section.values():
            candidate = value.get("answer")
            if candidate:
                texts.append(candidate)
    for turn in history:
        user_text = turn.get("user")
        if user_text:
            texts.append(user_text)

    resources: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for text in texts:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        if not looks_like_medication(cleaned):
            continue
        resource_id = hash_id("med", cleaned)
        if resource_id in seen_ids:
            continue
        seen_ids.add(resource_id)
        resource: Dict[str, Any] = {
            "resourceType": "MedicationStatement",
            "id": resource_id,
            "status": "active",
            "medicationCodeableConcept": {"text": cleaned},
            "effectiveDateTime": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        if patient_id:
            resource["subject"] = {"reference": f"Patient/{patient_id}"}
        resources.append(resource)
    return resources


def build_resources(
    structured_state: Dict[str, Dict[str, Any]],
    session_id: str,
    history: List[Dict[str, Optional[str]]],
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    context = structured_state.get("context", {})
    answers = structured_state.get("answers", {})

    resources: List[Dict[str, Any]] = []

    patient_resource, display_name = make_patient_resource(context, session_id)
    patient_id = patient_resource["id"] if patient_resource else None
    if patient_resource:
        resources.append(patient_resource)

    condition = make_condition_resource(context, patient_id, session_id)
    if condition:
        resources.append(condition)

    resources.extend(make_questionnaire_responses(answers, patient_id, session_id))
    resources.extend(make_medication_statements(answers, history, patient_id))

    return resources, patient_id, display_name


def resource_key(resource: Dict[str, Any]) -> str:
    resource_type = resource.get("resourceType", "Unknown")
    resource_id = resource.get("id")
    if not resource_id:
        resource_id = hash_id(resource_type.lower(), repr(resource))
        resource["id"] = resource_id
    return f"{resource_type}/{resource_id}"


# ---------------------------------------------------------------------------
# Medplum helpers
# ---------------------------------------------------------------------------

def get_medplum_token() -> Optional[str]:
    global MEDPLUM_TOKEN
    if MEDPLUM_TOKEN:
        return MEDPLUM_TOKEN

    client_id = os.getenv("MEDPLUM_CLIENT_ID")
    client_secret = os.getenv("MEDPLUM_CLIENT_SECRET")
    base_url = os.getenv("MEDPLUM_BASE_URL", "https://api.medplum.com")

    if not client_id or not client_secret:
        logger.info("Medplum credentials not configured - skipping EHR persistence")
        return None

    if "your_medplum" in client_id.lower() or "your_medplum" in client_secret.lower():
        logger.info("Medplum credentials are placeholders - skipping EHR persistence")
        return None

    try:
        response = requests.post(
            f"{base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        MEDPLUM_TOKEN = response.json().get("access_token")
        logger.info("Medplum authentication successful")
        return MEDPLUM_TOKEN
    except Exception as exc:
        logger.warning("Medplum authentication failed: %s", exc)
        return None


def save_to_medplum(resource: Dict[str, Any]) -> Optional[str]:
    token = get_medplum_token()
    if not token:
        return None

    base_url = os.getenv("MEDPLUM_BASE_URL", "https://api.medplum.com")
    resource_type = resource.get("resourceType")
    if not resource_type:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/fhir+json",
    }

    try:
        response = requests.post(
            f"{base_url}/fhir/R4/{resource_type}",
            headers=headers,
            json=resource,
            timeout=30,
        )
        response.raise_for_status()
        resource_id = response.json().get("id")
        if not resource_id:
            return None
        medplum_url = f"https://app.medplum.com/{resource_type}/{resource_id}"
        logger.info("Saved %s to Medplum: %s", resource_type, medplum_url)
        return medplum_url
    except Exception as exc:
        logger.error("Unable to save %s to Medplum: %s", resource_type, exc)
        return None


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


class PatientSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.conversation = IntakeConversation()
        self.welcome = self.conversation.initial_prompt()
        self.welcome_sent = False
        self.history: List[Dict[str, Optional[str]]] = []
        self.created_at = datetime.now()

        self.patient_id: Optional[str] = None
        self.patient_name: Optional[str] = None

        self.fhir_resource_map: Dict[str, Dict[str, Any]] = {}
        self.fhir_resources: List[Dict[str, Any]] = []
        self.medplum_ids: Dict[str, str] = {}
        self.medplum_links: List[str] = []

    def ensure_welcome(self) -> Optional[str]:
        if not self.welcome_sent:
            self.welcome_sent = True
            self.history.append({"timestamp": datetime.now().isoformat(), "user": None, "bot": self.welcome})
            return self.welcome
        return None

    def handle_user_message(self, user_message: str) -> str:
        reply = self.conversation.handle_message(user_message)
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "user": user_message,
                "bot": reply,
            }
        )
        return reply

    def refresh_resources(self) -> Tuple[List[Dict[str, Any]], List[str]]:
        structured = self.conversation.export_state()
        resources, patient_id, patient_name = build_resources(structured, self.session_id, self.history)

        if patient_id:
            self.patient_id = patient_id
        if patient_name:
            self.patient_name = patient_name

        new_resources: List[Dict[str, Any]] = []
        new_links: List[str] = []

        for resource in resources:
            key = resource_key(resource)
            if self.fhir_resource_map.get(key) == resource:
                continue
            self.fhir_resource_map[key] = resource
            new_resources.append(resource)

            medplum_link = self._save_to_medplum_once(key, resource)
            if medplum_link:
                new_links.append(medplum_link)

        self.fhir_resources = list(self.fhir_resource_map.values())
        self.medplum_links = list(self.medplum_ids.values())

        return new_resources, new_links

    def count_resources(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for resource in self.fhir_resources:
            resource_type = resource.get("resourceType", "Unknown")
            counts[resource_type] = counts.get(resource_type, 0) + 1
        return counts

    def _save_to_medplum_once(self, cache_key: str, resource: Dict[str, Any]) -> Optional[str]:
        if cache_key in self.medplum_ids:
            return None
        link = save_to_medplum(resource)
        if link:
            self.medplum_ids[cache_key] = link
        return link


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in SESSIONS:
        SESSIONS[session_id] = PatientSession(session_id)
        logger.info("Created new session: %s", session_id)

    session = SESSIONS[session_id]

    welcome = session.ensure_welcome()
    reply = session.handle_user_message(request.message)
    new_resources, new_links = session.refresh_resources()

    response_text = f"{welcome}\n\n{reply}" if welcome else reply

    return ChatResponse(
        response=response_text,
        session_id=session_id,
        fhir_resources=new_resources,
        medplum_links=new_links,
        decomposed_count=None,
    )


@app.get("/session/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS[session_id]
    return SessionInfo(
        session_id=session.session_id,
        patient_id=session.patient_id,
        patient_name=session.patient_name,
        created_at=session.created_at.isoformat(),
        message_count=len(session.history),
        fhir_resource_count=len(session.fhir_resources),
        resource_counts=session.count_resources(),
    )


@app.get("/session/{session_id}/resources")
async def get_session_resources(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS[session_id]
    return {
        "session_id": session.session_id,
        "patient_id": session.patient_id,
        "resources": session.fhir_resources,
        "medplum_links": session.medplum_links,
    }


@app.post("/session/{session_id}/reset")
async def reset_session(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    SESSIONS[session_id] = PatientSession(session_id)
    logger.info("Reset session: %s", session_id)
    return {"status": "reset", "session_id": session_id}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "agent_id": "intake-conversation",
        "active_sessions": len(SESSIONS),
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.getenv("PORT", "8005"))
    logger.info("Starting Angy Chatbot Backend on port %s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
