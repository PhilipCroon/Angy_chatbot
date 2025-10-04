#!/usr/bin/env python3
"""
FastAPI backend for chest pain presentation using Lang2FHIR + Medplum
Focuses on acute care workflow: chest pain chief complaint
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple
import os
import base64
import json
import requests
from dotenv import load_dotenv
import logging
from datetime import datetime
import uuid

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chest Pain Assessment with Lang2FHIR", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Global variables
ACCESS_TOKEN = None
MEDPLUM_TOKEN = None
SESSIONS = {}

# Request/Response models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    fhir_resources: List[Dict[str, Any]] = []
    medplum_links: List[str] = []

class PatientSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.patient_id = None
        self.patient_name = None
        self.history = []
        self.fhir_resources = []
        self.medplum_ids = {}
        self.created_at = datetime.now()

        # Chest pain assessment tracking
        self.has_patient_info = False
        self.has_chief_complaint = False
        self.has_vitals = False
        self.has_history = False

    def add_message(self, user_msg: str, bot_response: str, resources: List = None):
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "user": user_msg,
            "bot": bot_response
        })
        if resources:
            self.fhir_resources.extend(resources)

def get_access_token() -> str:
    """Get or refresh Lang2FHIR access token"""
    global ACCESS_TOKEN

    if ACCESS_TOKEN:
        return ACCESS_TOKEN

    username = os.getenv("PHENOML_USERNAME")
    password = os.getenv("PHENOML_PASSWORD")
    base_url = os.getenv("PHENOML_BASE_URL", "https://experiment.app.pheno.ml")

    if not username or not password:
        raise ValueError("Missing Lang2FHIR credentials")

    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode()

    auth_url = f"{base_url}/auth/token"
    headers = {
        "accept": "application/json",
        "authorization": f"Basic {basic_token}",
    }

    response = requests.post(auth_url, headers=headers, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Authentication failed: {response.text}")

    try:
        data = response.json()
        token = data.get("access_token") or data.get("token") if isinstance(data, dict) else data.strip()
    except:
        token = response.text.strip()

    if not token:
        raise RuntimeError("No access token received")

    ACCESS_TOKEN = token
    return token

def get_medplum_token() -> Optional[str]:
    """Get Medplum access token if configured"""
    global MEDPLUM_TOKEN

    if MEDPLUM_TOKEN:
        return MEDPLUM_TOKEN

    client_id = os.getenv("MEDPLUM_CLIENT_ID")
    client_secret = os.getenv("MEDPLUM_CLIENT_SECRET")
    base_url = os.getenv("MEDPLUM_BASE_URL", "https://api.medplum.com")

    if not client_id or not client_secret or "your_medplum" in client_id:
        logger.warning("Medplum not configured - resources will not be saved to EHR")
        return None

    try:
        auth_url = f"{base_url}/oauth2/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret
        }
        response = requests.post(auth_url, data=data, timeout=30)

        if response.status_code == 200:
            MEDPLUM_TOKEN = response.json().get("access_token")
            return MEDPLUM_TOKEN
        else:
            logger.error(f"Medplum auth failed: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Medplum connection error: {e}")
        return None

def call_lang2fhir_create(text: str, resource_type="auto") -> Dict[str, Any]:
    """Call Lang2FHIR to create a FHIR resource from text"""
    token = get_access_token()
    base_url = os.getenv("PHENOML_BASE_URL", "https://experiment.app.pheno.ml")

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
    }

    payload = {
        "text": text,
        "resource": resource_type,
        "version": "R4"
    }

    url = f"{base_url}/lang2fhir/create"
    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        logger.error(f"Lang2FHIR error: {response.text}")
        raise RuntimeError(f"Lang2FHIR failed: {response.text}")

    return response.json()

def save_to_medplum(resource: Dict[str, Any]) -> Optional[str]:
    """Save FHIR resource to Medplum and return the resource URL"""
    token = get_medplum_token()

    if not token:
        return None

    try:
        base_url = os.getenv("MEDPLUM_BASE_URL", "https://api.medplum.com")
        resource_type = resource.get("resourceType")

        if not resource_type:
            logger.error("No resourceType in FHIR resource")
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/fhir+json"
        }

        url = f"{base_url}/fhir/R4/{resource_type}"
        response = requests.post(url, headers=headers, json=resource, timeout=30)

        if response.status_code in [200, 201]:
            result = response.json()
            resource_id = result.get("id")
            if resource_id:
                # Return Medplum app URL
                medplum_url = f"https://app.medplum.com/{resource_type}/{resource_id}"
                logger.info(f"Created {resource_type} in Medplum: {medplum_url}")
                return medplum_url
        else:
            logger.error(f"Medplum create failed: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error saving to Medplum: {e}")
        return None

def process_chest_pain_message(message: str, session: PatientSession) -> Tuple[str, List[Dict], List[str]]:
    """
    Process chest pain presentation workflow
    Returns: (response_text, list_of_fhir_resources, list_of_medplum_urls)
    """
    message_lower = message.lower()
    created_resources = []
    medplum_links = []

    # Stage 1: Greeting and patient identification
    if not session.has_patient_info and any(word in message_lower for word in ["hello", "hi", "help", "start", "here"]):
        response = "Hello! I'm here to help document your visit. Let's start by confirming your information. Could you please provide your full name and date of birth?"

    elif not session.has_patient_info and ("name is" in message_lower or "i am" in message_lower or "born" in message_lower):
        try:
            patient_resource = call_lang2fhir_create(message, "Patient")
            created_resources.append(patient_resource)

            # Save to Medplum
            medplum_url = save_to_medplum(patient_resource)
            if medplum_url:
                medplum_links.append(medplum_url)

            # Extract patient name
            if "name" in patient_resource and patient_resource["name"]:
                name_obj = patient_resource["name"][0] if isinstance(patient_resource["name"], list) else patient_resource["name"]
                if "given" in name_obj and "family" in name_obj:
                    given = name_obj["given"][0] if isinstance(name_obj["given"], list) else name_obj["given"]
                    session.patient_name = f"{given} {name_obj['family']}"

            session.has_patient_info = True
            response = f"Thank you. What brings you in today? What's your main concern or chief complaint?"

        except Exception as e:
            logger.error(f"Error creating patient: {e}")
            response = "I had trouble recording that. Could you provide your name and date of birth again?"

    # Stage 2: Chief complaint (chest pain)
    elif not session.has_chief_complaint and any(word in message_lower for word in ["chest pain", "chest", "pain", "hurt", "pressure", "tightness", "discomfort"]):
        try:
            # Create Encounter for the visit
            encounter_text = f"Patient {session.patient_name or 'presents'} with chief complaint: {message}"
            encounter_resource = call_lang2fhir_create(encounter_text, "Encounter")
            created_resources.append(encounter_resource)

            medplum_url = save_to_medplum(encounter_resource)
            if medplum_url:
                medplum_links.append(medplum_url)

            # Create Condition for chest pain
            condition_resource = call_lang2fhir_create(message, "Condition")
            created_resources.append(condition_resource)

            medplum_url = save_to_medplum(condition_resource)
            if medplum_url:
                medplum_links.append(medplum_url)

            session.has_chief_complaint = True
            response = "I understand you're experiencing chest pain. Let me get your vital signs. Can you tell me your blood pressure, heart rate, temperature, and oxygen saturation if you know them?"

        except Exception as e:
            logger.error(f"Error creating encounter/condition: {e}")
            response = "I've noted your chest pain. Can you provide your current vital signs?"

    # Stage 3: Vital signs
    elif not session.has_vitals and any(word in message_lower for word in ["bp", "blood pressure", "heart rate", "hr", "pulse", "temp", "temperature", "spo2", "oxygen", "vital"]):
        try:
            # Create Observation resources for vitals
            observation_resource = call_lang2fhir_create(f"Vital signs: {message}", "Observation")
            created_resources.append(observation_resource)

            medplum_url = save_to_medplum(observation_resource)
            if medplum_url:
                medplum_links.append(medplum_url)

            session.has_vitals = True
            response = "Thank you. Now, can you describe your chest pain? When did it start? What does it feel like? Does anything make it better or worse? Any radiation to arms, jaw, or back?"

        except Exception as e:
            logger.error(f"Error creating vitals: {e}")
            response = "I've noted your vitals. Can you describe your chest pain in detail?"

    # Stage 4: Detailed history and characteristics
    elif not session.has_history:
        try:
            # Create detailed Condition with characteristics
            condition_detail = call_lang2fhir_create(f"Chest pain characteristics: {message}", "Condition")
            created_resources.append(condition_detail)

            medplum_url = save_to_medplum(condition_detail)
            if medplum_url:
                medplum_links.append(medplum_url)

            session.has_history = True
            response = "Do you have any relevant medical history? Such as previous heart problems, diabetes, hypertension, high cholesterol, smoking history, or current medications?"

        except Exception as e:
            logger.error(f"Error creating condition detail: {e}")
            response = "I've noted that. Do you have any relevant medical history or take any medications?"

    # Stage 5: Past medical history and medications
    elif any(word in message_lower for word in ["history", "medication", "medicine", "take", "diabetes", "hypertension", "cholesterol", "smoke", "smoking"]):
        try:
            # Try to create Condition for PMH
            if any(word in message_lower for word in ["diabetes", "hypertension", "cholesterol", "heart", "stroke"]):
                pmh_resource = call_lang2fhir_create(f"Past medical history: {message}", "Condition")
                created_resources.append(pmh_resource)

                medplum_url = save_to_medplum(pmh_resource)
                if medplum_url:
                    medplum_links.append(medplum_url)

            # Try to create MedicationRequest for medications
            if any(word in message_lower for word in ["medication", "medicine", "take", "mg", "pill", "tablet"]):
                med_resource = call_lang2fhir_create(f"Current medications: {message}", "MedicationRequest")
                created_resources.append(med_resource)

                medplum_url = save_to_medplum(med_resource)
                if medplum_url:
                    medplum_links.append(medplum_url)

            response = "Thank you. Based on this presentation, you should be evaluated immediately. Do you have any allergies to medications?"

        except Exception as e:
            logger.error(f"Error creating PMH/medications: {e}")
            response = "I've noted that information. Do you have any allergies?"

    # Stage 6: Allergies
    elif any(word in message_lower for word in ["allergy", "allergic", "reaction"]):
        try:
            allergy_resource = call_lang2fhir_create(message, "AllergyIntolerance")
            created_resources.append(allergy_resource)

            medplum_url = save_to_medplum(allergy_resource)
            if medplum_url:
                medplum_links.append(medplum_url)

            response = "I've completed the chest pain assessment. Your information has been documented. Based on your symptoms, you need immediate medical evaluation. Is there anything else you need to tell me?"

        except Exception as e:
            logger.error(f"Error creating allergy: {e}")
            response = "Thank you. Your chest pain assessment is complete."

    elif any(word in message_lower for word in ["no", "nothing", "that's all", "done"]):
        response = "Your chest pain visit has been fully documented in the system. Please proceed to the examination room for physician evaluation."

    elif any(word in message_lower for word in ["thank", "thanks"]):
        response = "You're welcome. Please get immediate medical attention for your chest pain."

    else:
        # Generic response - try to process as observation
        response = "I've noted that information. Please continue describing your symptoms or medical history."

    return response, created_resources, medplum_links

@app.get("/")
async def root():
    return {"status": "running", "service": "Chest Pain Assessment with Lang2FHIR"}

@app.get("/health")
async def health_check():
    medplum_configured = bool(
        os.getenv("MEDPLUM_CLIENT_ID") and
        os.getenv("MEDPLUM_CLIENT_SECRET") and
        "your_medplum" not in os.getenv("MEDPLUM_CLIENT_ID", "")
    )

    return {
        "status": "healthy",
        "lang2fhir_configured": bool(os.getenv("PHENOML_USERNAME")),
        "medplum_configured": medplum_configured,
        "base_url": os.getenv("PHENOML_BASE_URL", "https://experiment.app.pheno.ml"),
        "medplum_url": os.getenv("MEDPLUM_BASE_URL", "https://api.medplum.com")
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        # Get or create session
        if request.session_id and request.session_id in SESSIONS:
            session = SESSIONS[request.session_id]
        else:
            session_id = request.session_id or str(uuid.uuid4())
            session = PatientSession(session_id)
            SESSIONS[session_id] = session

        logger.info(f"Processing chest pain message for session {session.session_id}: {request.message[:50]}...")

        # Process the message
        response_text, fhir_resources, medplum_links = process_chest_pain_message(request.message, session)

        # Add to session history
        session.add_message(request.message, response_text, fhir_resources)

        return ChatResponse(
            response=response_text,
            session_id=session.session_id,
            fhir_resources=fhir_resources,
            medplum_links=medplum_links
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    if session_id not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")

    session = SESSIONS[session_id]
    return {
        "session_id": session.session_id,
        "patient_id": session.patient_id,
        "patient_name": session.patient_name,
        "created_at": session.created_at.isoformat(),
        "message_count": len(session.history),
        "fhir_resources_created": len(session.fhir_resources),
        "resources": session.fhir_resources,
        "medplum_ids": session.medplum_ids
    }

if __name__ == "__main__":
    import uvicorn

    if not os.getenv("PHENOML_USERNAME"):
        print("❌ ERROR: Lang2FHIR credentials not configured")
        exit(1)

    print("\n" + "=" * 60)
    print("Starting Chest Pain Assessment API")
    print("=" * 60)
    print(f"Lang2FHIR URL: {os.getenv('PHENOML_BASE_URL')}")
    print(f"API Docs: http://localhost:8002/docs")
    print(f"Health Check: http://localhost:8002/health")

    medplum_configured = "your_medplum" not in os.getenv("MEDPLUM_CLIENT_ID", "your_medplum")
    if medplum_configured:
        print(f"✅ Medplum: {os.getenv('MEDPLUM_BASE_URL')}")
        print("   Resources will be saved to Medplum EHR")
    else:
        print("⚠️  Medplum: Not configured")
        print("   Resources will be created but not saved to EHR")
        print("   To enable: Set MEDPLUM_CLIENT_ID and MEDPLUM_CLIENT_SECRET in .env")
    print("-" * 60)

    uvicorn.run(
        "app_chest_pain:app",
        host="0.0.0.0",
        port=8002,
        reload=True,
        log_level="info"
    )
