"""Gradio interface for Angy with scripted intake + FHIR/Medplum integration."""

import json
import uuid
from typing import Dict, List, Tuple, Any
import requests

import gradio as gr

# Backend configuration
BACKEND_URL = "http://localhost:8005"

# Global session state
session_state = {
    "session_id": None,
    "all_resources": [],
    "all_medplum_links": [],
    "message_count": 0,
    "resource_index": {},
}


def check_backend_health() -> bool:
    """Check if the backend is running"""
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def chat_with_backend(message: str, session_id: str = None) -> Dict[str, Any]:
    """Send a message to the FastAPI backend and get response with FHIR resources"""
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id

    try:
        response = requests.post(f"{BACKEND_URL}/chat", json=payload, timeout=60)

        if response.status_code == 200:
            return response.json()
        else:
            return {
                "response": f"❌ Backend error: {response.status_code} - {response.text}",
                "session_id": session_id or str(uuid.uuid4()),
                "fhir_resources": [],
                "medplum_links": [],
            }
    except requests.exceptions.Timeout:
        return {
            "response": "⏱️ Request timed out. The backend might be processing a complex message. Please try again.",
            "session_id": session_id or str(uuid.uuid4()),
            "fhir_resources": [],
            "medplum_links": [],
        }
    except Exception as e:
        return {
            "response": f"❌ Error connecting to backend: {str(e)}",
            "session_id": session_id or str(uuid.uuid4()),
            "fhir_resources": [],
            "medplum_links": [],
        }


def get_session_info(session_id: str) -> Dict[str, Any]:
    """Get session information from backend"""
    try:
        response = requests.get(f"{BACKEND_URL}/session/{session_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
        return {}
    except:
        return {}


def format_resource_display(resources: List[Dict]) -> str:
    """Format FHIR resources for display"""
    if not resources:
        return "**No FHIR resources created yet.**\n\n_Resources will appear here as the conversation progresses._"

    lines = [f"### 📋 FHIR Resources Created ({len(resources)})\n"]

    # Group by resource type
    by_type = {}
    for resource in resources:
        resource_type = resource.get("resourceType", "Unknown")
        if resource_type not in by_type:
            by_type[resource_type] = []
        by_type[resource_type].append(resource)

    for resource_type, type_resources in by_type.items():
        lines.append(f"\n#### {resource_type} ({len(type_resources)})")

        for i, resource in enumerate(type_resources, 1):
            resource_id = resource.get("id", "unknown")
            lines.append(f"\n**{i}. {resource_type}/{resource_id}**")

            # Show key fields based on type
            if resource_type == "Patient":
                if "name" in resource and resource["name"]:
                    name_obj = resource["name"][0]
                    given = " ".join(name_obj.get("given", []))
                    family = name_obj.get("family", "")
                    lines.append(f"- Name: {given} {family}")
                if "birthDate" in resource:
                    lines.append(f"- Birth Date: {resource['birthDate']}")
                if "gender" in resource:
                    lines.append(f"- Gender: {resource['gender']}")

            elif resource_type == "Condition":
                if "code" in resource and "coding" in resource["code"]:
                    coding = resource["code"]["coding"][0]
                    display = coding.get("display", coding.get("code", "Unknown"))
                    lines.append(f"- Condition: {display}")
                if "clinicalStatus" in resource:
                    status = resource["clinicalStatus"].get("coding", [{}])[0].get("code", "unknown")
                    lines.append(f"- Status: {status}")

            elif resource_type == "MedicationRequest":
                if "medicationCodeableConcept" in resource:
                    med_concept = resource["medicationCodeableConcept"]
                    if "coding" in med_concept:
                        coding = med_concept["coding"][0]
                        display = coding.get("display", coding.get("code", "Unknown"))
                        lines.append(f"- Medication: {display}")
                if "dosageInstruction" in resource and resource["dosageInstruction"]:
                    dosage = resource["dosageInstruction"][0]
                    lines.append(f"- Dosage: {dosage.get('text', 'Not specified')}")

            elif resource_type == "Observation":
                if "code" in resource and "coding" in resource["code"]:
                    coding = resource["code"]["coding"][0]
                    display = coding.get("display", coding.get("code", "Unknown"))
                    lines.append(f"- Observation: {display}")
                if "valueString" in resource:
                    lines.append(f"- Value: {resource['valueString']}")
                elif "valueQuantity" in resource:
                    value = resource["valueQuantity"]
                    lines.append(f"- Value: {value.get('value')} {value.get('unit', '')}")

            elif resource_type == "AllergyIntolerance":
                if "code" in resource and "coding" in resource["code"]:
                    coding = resource["code"]["coding"][0]
                    display = coding.get("display", coding.get("code", "Unknown"))
                    lines.append(f"- Allergen: {display}")
                if "reaction" in resource and resource["reaction"]:
                    manifestation = resource["reaction"][0].get("manifestation", [{}])[0]
                    if "coding" in manifestation:
                        reaction_display = manifestation["coding"][0].get("display", "Unknown")
                        lines.append(f"- Reaction: {reaction_display}")

            # Show JSON toggle
            json_str = json.dumps(resource, indent=2)
            lines.append(f"\n<details><summary>View JSON</summary>\n\n```json\n{json_str}\n```\n</details>")

    return "\n".join(lines)


def format_medplum_links(links: List[str]) -> str:
    """Format Medplum links for display"""
    if not links:
        return "**No Medplum links yet.**\n\n_Links will appear here if Medplum is configured and resources are saved._"

    lines = [f"### 🏥 Medplum EHR Links ({len(links)})\n"]
    lines.append("Click these links to view resources in the Medplum EHR:\n")

    for i, link in enumerate(links, 1):
        # Extract resource type and ID from URL
        parts = link.split("/")
        if len(parts) >= 2:
            resource_type = parts[-2]
            resource_id = parts[-1]
            lines.append(f"{i}. [{resource_type}/{resource_id}]({link})")
        else:
            lines.append(f"{i}. [View Resource]({link})")

    return "\n".join(lines)


def format_statistics(session_id: str) -> str:
    """Format session statistics"""
    info = get_session_info(session_id)

    if not info:
        return "**Session Statistics**\n\n_Loading..._"

    lines = ["### 📊 Session Statistics\n"]
    lines.append(f"- **Session ID**: `{info.get('session_id', 'unknown')}`")
    lines.append(f"- **Messages**: {info.get('message_count', 0)}")
    lines.append(f"- **FHIR Resources**: {info.get('fhir_resource_count', 0)}")

    if info.get('patient_id'):
        lines.append(f"- **Patient ID**: `{info['patient_id']}`")
    if info.get('patient_name'):
        lines.append(f"- **Patient Name**: {info['patient_name']}")

    if info.get('resource_counts'):
        lines.append("\n**Resource Breakdown**:")
        for resource_type, count in info['resource_counts'].items():
            lines.append(f"- {resource_type}: {count}")

    return "\n".join(lines)


def chat(message: str, history: List[Tuple[str, str]]) -> Tuple[str, str, str, str]:
    """
    Handle chat interaction.

    Args:
        message: User's message
        history: Chat history (Gradio format)

    Returns:
        Tuple of (response, resources_display, medplum_links_display, statistics)
    """
    global session_state

    # Initialize session if needed
    if session_state["session_id"] is None:
        session_state["session_id"] = str(uuid.uuid4())

    # Call backend
    result = chat_with_backend(message, session_state["session_id"])

    # Update session state
    session_state["session_id"] = result["session_id"]
    session_state["message_count"] += 1

    # Accumulate resources and links
    if result.get("fhir_resources"):
        for resource in result["fhir_resources"]:
            resource_type = resource.get("resourceType", "Unknown")
            resource_id = resource.get("id") or ""
            key = f"{resource_type}/{resource_id}"
            session_state["resource_index"][key] = resource
        session_state["all_resources"] = list(session_state["resource_index"].values())
    if result.get("medplum_links"):
        session_state["all_medplum_links"].extend(result["medplum_links"])

    # Format response
    response = result["response"]

    # Add decomposition notice if applicable
    if result.get("decomposed_count") and result["decomposed_count"] > 1:
        response = f"_✂️ Message decomposed into {result['decomposed_count']} parts for better processing_\n\n{response}"

    # Format displays
    resources_display = format_resource_display(session_state["all_resources"])
    medplum_display = format_medplum_links(session_state["all_medplum_links"])
    statistics = format_statistics(session_state["session_id"])

    return response, resources_display, medplum_display, statistics


def reset_session():
    """Reset the session"""
    global session_state
    session_state = {
        "session_id": None,
        "all_resources": [],
        "all_medplum_links": [],
        "message_count": 0,
        "resource_index": {},
    }
    return (
        None,  # Clear chat
        format_resource_display([]),
        format_medplum_links([]),
        "**Session Statistics**\n\n_Start a new conversation to see statistics_"
    )


# Custom CSS
custom_css = """
.gradio-container {
    font-family: 'Inter', sans-serif;
}
.markdown-text details {
    margin-top: 0.5em;
    margin-bottom: 0.5em;
}
.markdown-text summary {
    cursor: pointer;
    font-weight: 500;
    color: #2563eb;
}
.markdown-text summary:hover {
    color: #1d4ed8;
}
"""

# Build Gradio interface
with gr.Blocks(css=custom_css, title="Angy - Medical Intake with FHIR", theme=gr.themes.Soft()) as demo:
    gr.Markdown("""
    # 🏥 Angy - Medical Intake Assistant
    ### with FHIR Integration & Medplum EHR

    This chatbot uses AI to help collect your medical information and automatically creates FHIR-compliant health records.

    **Features:**
    - 🤖 Intelligent conversation with PhenoML agent
    - ✂️ Automatic decomposition of complex medical information
    - 📋 Real-time FHIR resource creation
    - 🏥 Optional Medplum EHR storage
    """)

    # Check backend health
    if not check_backend_health():
        gr.Markdown("""
        ⚠️ **Backend not running!**

        Please start the backend first:
        ```bash
        python app_angy_intake_agent.py
        ```
        """)
    else:
        gr.Markdown("✅ **Backend connected** - Ready to chat!")

    with gr.Row():
        # Left column: Chat interface
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(
                label="Conversation",
                height=500,
                show_label=True,
                avatar_images=(None, "https://cdn-icons-png.flaticon.com/512/4712/4712109.png")
            )

            with gr.Row():
                msg = gr.Textbox(
                    label="Your message",
                    placeholder="Type your message here...",
                    lines=2,
                    scale=4
                )
                submit = gr.Button("Send", variant="primary", scale=1)

            with gr.Row():
                clear = gr.Button("🔄 Reset Session", variant="secondary")

            gr.Markdown("""
            ### 💡 Try these examples:
            - "My name is John Smith"
            - "I was born on January 15, 1980"
            - "I've been having chest pain and shortness of breath"
            - "I have diabetes, high blood pressure, and high cholesterol. I take metformin 1000mg twice daily, lisinopril 20mg once daily, and atorvastatin 40mg at bedtime."
            """)

        # Right column: FHIR resources and statistics
        with gr.Column(scale=1):
            statistics_display = gr.Markdown(
                format_statistics(""),
                label="Statistics"
            )

            resources_display = gr.Markdown(
                format_resource_display([]),
                label="FHIR Resources"
            )

            medplum_display = gr.Markdown(
                format_medplum_links([]),
                label="Medplum Links"
            )

    # Event handlers
    def handle_submit(message, history):
        """Handle message submission"""
        if not message.strip():
            return history, "", "", "", ""

        response, resources, medplum, stats = chat(message, history)

        # Append to history
        history = history + [(message, response)]

        return history, "", resources, medplum, stats

    submit.click(
        handle_submit,
        inputs=[msg, chatbot],
        outputs=[chatbot, msg, resources_display, medplum_display, statistics_display]
    )

    msg.submit(
        handle_submit,
        inputs=[msg, chatbot],
        outputs=[chatbot, msg, resources_display, medplum_display, statistics_display]
    )

    clear.click(
        reset_session,
        outputs=[chatbot, resources_display, medplum_display, statistics_display]
    )

    gr.Markdown("""
    ---
    ### 📚 Documentation
    - **Integration Report**: See `INTEGRATION_REPORT.md` for complete technical details
    - **Backend**: FastAPI backend with PhenoML agent integration
    - **Message Decomposition**: Automatically handles complex medical inputs
    - **FHIR Standard**: Resources follow FHIR R4 specification

    **Backend URL**: `http://localhost:8005`
    """)

if __name__ == "__main__":
    print("=" * 80)
    print("Starting Angy Gradio Interface with FHIR Integration")
    print("=" * 80)
    print()
    print("Backend URL:", BACKEND_URL)
    print()

    # Check backend
    if check_backend_health():
        print("✅ Backend is running and healthy!")
        health = requests.get(f"{BACKEND_URL}/health").json()
        print(f"   Agent ID: {health.get('agent_id')}")
        print(f"   Active Sessions: {health.get('active_sessions')}")
    else:
        print("⚠️  WARNING: Backend not detected!")
        print("   Please start the backend:")
        print("   python app_angy_intake_agent.py")

    print()
    print("=" * 80)
    print()

    # Launch Gradio
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )
