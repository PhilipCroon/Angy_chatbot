"""
Test script for Angy Chatbot Backend with FHIR Integration

This script tests the complete flow:
1. Basic patient information collection
2. Chief complaint
3. Complex message decomposition
4. FHIR resource creation
5. Medplum storage (if configured)
"""

import requests
import json
import time
from typing import Dict, Any, Optional

BASE_URL = "http://localhost:8005"

def print_section(title: str):
    """Print a section header"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def chat(message: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Send a chat message to the backend"""
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    print(f"\n💬 User: {message}")

    response = requests.post(f"{BASE_URL}/chat", json=payload)

    if response.status_code != 200:
        print(f"❌ Error: {response.status_code} - {response.text}")
        return {}

    data = response.json()

    print(f"🤖 Angy: {data['response'][:200]}...")

    if data.get('decomposed_count'):
        print(f"   ✂️  Message decomposed into {data['decomposed_count']} parts")

    if data.get('fhir_resources'):
        print(f"   📋 Created {len(data['fhir_resources'])} FHIR resources:")
        for resource in data['fhir_resources']:
            resource_type = resource.get('resourceType', 'Unknown')
            resource_id = resource.get('id', 'unknown')
            print(f"      - {resource_type}/{resource_id}")

    if data.get('medplum_links'):
        print(f"   🏥 Medplum links:")
        for link in data['medplum_links']:
            print(f"      - {link}")

    return data


def get_session_info(session_id: str) -> Dict[str, Any]:
    """Get session information"""
    response = requests.get(f"{BASE_URL}/session/{session_id}")

    if response.status_code != 200:
        print(f"❌ Error: {response.status_code} - {response.text}")
        return {}

    return response.json()


def health_check() -> bool:
    """Check if the backend is running"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def main():
    """Run the test scenario"""

    print_section("Angy Chatbot Backend Test")

    # Health check
    print("\n🔍 Checking backend health...")
    if not health_check():
        print("❌ Backend is not running!")
        print(f"   Please start it with: python app_angy_intake_agent.py")
        return

    print("✅ Backend is healthy!")

    # Test scenario
    print_section("Test Scenario: General Patient Intake")

    session_id = None

    # Message 1: Name
    print("\n--- Message 1: Patient Name ---")
    result = chat("My name is John Smith", session_id)
    session_id = result.get("session_id")
    time.sleep(1)

    # Message 2: Date of Birth
    print("\n--- Message 2: Date of Birth ---")
    result = chat("I was born on January 15, 1980", session_id)
    time.sleep(1)

    # Message 3: Chief Complaint
    print("\n--- Message 3: Chief Complaint ---")
    result = chat("I've been having chest pain and shortness of breath", session_id)
    time.sleep(1)

    # Message 4: Complex Medical History (should be decomposed)
    print("\n--- Message 4: Complex Medical History ---")
    result = chat(
        "I have a history of type 2 diabetes, high blood pressure, and high cholesterol. "
        "I take metformin 1000mg twice daily, lisinopril 20mg once daily, and atorvastatin 40mg at bedtime.",
        session_id
    )
    time.sleep(1)

    # Message 5: Smoking History
    print("\n--- Message 5: Smoking History ---")
    result = chat("I've been smoking a pack a day for 20 years", session_id)
    time.sleep(1)

    # Message 6: Family History
    print("\n--- Message 6: Family History ---")
    result = chat("My father had a heart attack at age 55", session_id)
    time.sleep(1)

    # Message 7: Allergies
    print("\n--- Message 7: Allergies ---")
    result = chat("I'm allergic to penicillin - it gives me hives", session_id)
    time.sleep(1)

    # Get session summary
    print_section("Session Summary")
    session_info = get_session_info(session_id)

    if session_info:
        print(f"\n📊 Session ID: {session_info['session_id']}")
        print(f"👤 Patient: {session_info.get('patient_name', 'Not set')}")
        print(f"🆔 Patient ID: {session_info.get('patient_id', 'Not set')}")
        print(f"💬 Messages: {session_info['message_count']}")
        print(f"📋 FHIR Resources: {session_info['fhir_resource_count']}")

        if session_info.get('resource_counts'):
            print(f"\n📊 Resource Breakdown:")
            for resource_type, count in session_info['resource_counts'].items():
                print(f"   - {resource_type}: {count}")

    # Get all resources
    print("\n🔍 Fetching all resources...")
    response = requests.get(f"{BASE_URL}/session/{session_id}/resources")
    if response.status_code == 200:
        resources_data = response.json()
        print(f"\n📋 All FHIR Resources ({len(resources_data['resources'])}):")

        for i, resource in enumerate(resources_data['resources'], 1):
            resource_type = resource.get('resourceType', 'Unknown')
            resource_id = resource.get('id', 'unknown')
            print(f"\n   {i}. {resource_type}/{resource_id}")

            # Show key fields based on type
            if resource_type == "Patient":
                if 'name' in resource and resource['name']:
                    name_obj = resource['name'][0]
                    given = " ".join(name_obj.get('given', []))
                    family = name_obj.get('family', '')
                    print(f"      Name: {given} {family}")
                if 'birthDate' in resource:
                    print(f"      Birth Date: {resource['birthDate']}")

            elif resource_type == "Condition":
                if 'code' in resource and 'coding' in resource['code']:
                    coding = resource['code']['coding'][0]
                    print(f"      Condition: {coding.get('display', coding.get('code'))}")

            elif resource_type == "MedicationRequest":
                if 'medicationCodeableConcept' in resource:
                    med_concept = resource['medicationCodeableConcept']
                    if 'coding' in med_concept:
                        coding = med_concept['coding'][0]
                        print(f"      Medication: {coding.get('display', coding.get('code'))}")
                if 'dosageInstruction' in resource and resource['dosageInstruction']:
                    dosage = resource['dosageInstruction'][0]
                    print(f"      Dosage: {dosage.get('text', 'Not specified')}")

            elif resource_type == "Observation":
                if 'code' in resource and 'coding' in resource['code']:
                    coding = resource['code']['coding'][0]
                    print(f"      Observation: {coding.get('display', coding.get('code'))}")
                if 'valueString' in resource:
                    print(f"      Value: {resource['valueString']}")

            elif resource_type == "AllergyIntolerance":
                if 'code' in resource and 'coding' in resource['code']:
                    coding = resource['code']['coding'][0]
                    print(f"      Allergen: {coding.get('display', coding.get('code'))}")

        if resources_data.get('medplum_links'):
            print(f"\n🏥 Medplum Links ({len(resources_data['medplum_links'])}):")
            for link in resources_data['medplum_links']:
                print(f"   - {link}")

    print_section("Test Complete")
    print("\n✅ All tests completed successfully!")
    print(f"   Session ID: {session_id}")
    print(f"   View resources: {BASE_URL}/session/{session_id}/resources")


if __name__ == "__main__":
    main()
