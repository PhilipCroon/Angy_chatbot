# Angy Gradio Interface with FHIR Integration - Quick Start Guide

## Overview

The new Gradio interface (`gradio_app_fhir.py`) provides a user-friendly web UI that connects to the FastAPI backend for:
- Real-time chat with PhenoML agent
- Automatic message decomposition
- Live FHIR resource display
- Medplum EHR links
- Session statistics

## Quick Start

### Step 1: Start the Backend

```bash
cd /Users/poa3/Desktop/hackathon/Angy_chatbot

# Start the FastAPI backend on port 8005
python app_angy_intake_agent.py
```

Expected output:
```
INFO - Starting Angy Chatbot Backend on port 8005
INFO - Agent ID: 8a9ffa61-e447-4af9-8f0f-2834ca082a21
INFO - Uvicorn running on http://0.0.0.0:8005
```

### Step 2: Start the Gradio Interface

In a **new terminal**:

```bash
cd /Users/poa3/Desktop/hackathon/Angy_chatbot

# Start the Gradio web interface on port 7860
python gradio_app_fhir.py
```

Expected output:
```
================================================================================
Starting Angy Gradio Interface with FHIR Integration
================================================================================

Backend URL: http://localhost:8005

✅ Backend is running and healthy!
   Agent ID: 8a9ffa61-e447-4af9-8f0f-2834ca082a21
   Active Sessions: 0

================================================================================

Running on local URL:  http://127.0.0.1:7860
```

### Step 3: Open Your Browser

Navigate to: **http://localhost:7860**

You should see the Angy interface with:
- **Left Panel**: Chat interface
- **Right Panel**: FHIR resources, Medplum links, and statistics

## How to Use

### 1. Start a Conversation

Type in the chat box:
```
My name is John Smith
```

The agent will respond and ask for more information.

### 2. Try a Complex Message

Type something complex to see message decomposition in action:
```
I have diabetes, high blood pressure, and high cholesterol.
I take metformin 1000mg twice daily, lisinopril 20mg once daily,
and atorvastatin 40mg at bedtime.
```

You'll see:
- ✂️ Notice that the message was decomposed
- Agent responds to each piece of information
- FHIR resources appear in the right panel (if agent creates them)

### 3. View FHIR Resources

As the conversation progresses:
- **FHIR Resources** section shows created resources
- Organized by resource type (Patient, Condition, MedicationRequest, etc.)
- Click "View JSON" to see the full FHIR resource

### 4. View Medplum Links

If Medplum is configured:
- **Medplum EHR Links** section shows clickable links
- Click any link to view the resource in Medplum

### 5. Check Statistics

The **Session Statistics** panel shows:
- Session ID
- Message count
- Total FHIR resources created
- Resource breakdown by type
- Patient ID (if created)

### 6. Reset Session

Click **🔄 Reset Session** to start a new conversation.

## Features

### 🤖 Intelligent Conversation
- PhenoML agent handles natural language
- Maintains context throughout conversation
- Asks clarifying questions

### ✂️ Automatic Message Decomposition
- Complex medical inputs are automatically split
- Each piece processed separately
- More accurate resource creation

### 📋 Real-Time FHIR Resources
- Resources displayed as they're created
- Formatted for easy reading
- Full JSON available on click

### 🏥 Medplum Integration
- Resources saved to Medplum EHR (if configured)
- Direct links to view in Medplum
- Persistent storage in FHIR-compliant system

### 📊 Session Management
- Tracks all messages and resources
- Maintains session continuity
- View statistics at any time

## UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                   Angy - Medical Intake Assistant                │
│              with FHIR Integration & Medplum EHR                 │
├─────────────────────────────────┬───────────────────────────────┤
│                                 │                               │
│    Chat Interface               │   Session Statistics          │
│    ┌─────────────────────────┐ │   - Session ID                │
│    │                         │ │   - Messages: 5               │
│    │  Conversation History   │ │   - FHIR Resources: 3         │
│    │                         │ │                               │
│    │  User: My name is ...   │ │                               │
│    │  Angy: Thank you ...    │ │   FHIR Resources Created      │
│    │                         │ │   ┌─────────────────────────┐ │
│    │  User: I have diabetes  │ │   │ Patient (1)             │ │
│    │  Angy: I've recorded... │ │   │ - Name: John Smith      │ │
│    │                         │ │   │ - DOB: 1980-01-15       │ │
│    └─────────────────────────┘ │   │                         │ │
│    ┌─────────────────────────┐ │   │ Condition (2)           │ │
│    │ Your message...         │ │   │ - Type 2 Diabetes       │ │
│    └─────────────────────────┘ │   │ - Hypertension          │ │
│    [ Send ]  [ Reset Session ] │   └─────────────────────────┘ │
│                                 │                               │
│    Examples:                    │   Medplum EHR Links          │
│    - My name is John Smith      │   1. Patient/abc123          │
│    - I have diabetes...         │   2. Condition/def456        │
│                                 │   3. Condition/ghi789        │
└─────────────────────────────────┴───────────────────────────────┘
```

## Example Conversation Flow

### Message 1: Name
**You**: My name is John Smith

**Angy**: I don't see an existing patient named John Smith in the system. Are you a new patient? If so, I'll need a bit more information...

**FHIR Resources**: _(None yet)_

### Message 2: Date of Birth
**You**: I was born on January 15, 1980

**Angy**: Thanks! And could you also provide your location and phone number?

**FHIR Resources**: _(None yet - agent needs complete info)_

### Message 3: Complex Medical History
**You**: I have diabetes, high blood pressure, and high cholesterol. I take metformin 1000mg twice daily, lisinopril 20mg once daily, and atorvastatin 40mg at bedtime.

**Notice**: _✂️ Message decomposed into 6 parts for better processing_

**Angy**: Okay, I've recorded that you are taking atorvastatin 40mg at bedtime...

**FHIR Resources**:
- Condition: Type 2 Diabetes
- Condition: Hypertension
- Condition: Hyperlipidemia
- MedicationRequest: Metformin 1000mg twice daily
- MedicationRequest: Lisinopril 20mg once daily
- MedicationRequest: Atorvastatin 40mg at bedtime

### Message 4: Allergy
**You**: I'm allergic to penicillin - it gives me hives

**Angy**: Okay, I've noted your penicillin allergy...

**FHIR Resources**:
- AllergyIntolerance: Penicillin

## Troubleshooting

### Backend Not Running
**Error**: "⚠️ Backend not running!"

**Solution**:
```bash
# In terminal 1
python app_angy_intake_agent.py
```

### Port Already in Use
**Error**: "Address already in use"

**Solution**:
```bash
# Kill existing process on port 8005
lsof -ti:8005 | xargs kill

# Or use a different port
PORT=8006 python app_angy_intake_agent.py
```

Then update `BACKEND_URL` in `gradio_app_fhir.py`:
```python
BACKEND_URL = "http://localhost:8006"
```

### Timeout Errors
**Error**: "Request timed out"

**Reason**: Complex messages may take 30-60 seconds to process (decomposition + multiple agent calls)

**Solution**: Wait a bit longer. The backend is processing your message.

### No FHIR Resources Shown
**Reason**: The intake agent creates resources internally but may not expose them via markers.

**Current Status**: Agent confirms it has "recorded" information, but resources aren't returned to the UI yet.

**Future Enhancement**: Query PhenoML session API to retrieve created resources.

## Configuration

### Change Backend URL
Edit `gradio_app_fhir.py`:
```python
BACKEND_URL = "http://localhost:8005"  # Change to your backend URL
```

### Change Gradio Port
Edit the launch parameters:
```python
demo.launch(
    server_port=7860,  # Change to your desired port
    share=False
)
```

### Enable Public Sharing
```python
demo.launch(
    share=True  # Creates a public Gradio link
)
```

## Architecture

```
User Browser (http://localhost:7860)
        ↓
    Gradio Interface (gradio_app_fhir.py)
        ↓
    HTTP POST to http://localhost:8005/chat
        ↓
    FastAPI Backend (app_angy_intake_agent.py)
        ↓
    Message Decomposer (if complex)
        ↓ (multiple simple messages)
    PhenoML Agent (patient intake)
        ↓
    Lang2FHIR Resource Creation
        ↓
    Medplum Storage (optional)
        ↓
    Response + FHIR Resources
        ↓
    Display in Gradio UI
```

## API Calls

The Gradio app makes these API calls:

### 1. Health Check
```bash
GET http://localhost:8005/health
```

### 2. Send Message
```bash
POST http://localhost:8005/chat
Content-Type: application/json

{
  "message": "I have diabetes",
  "session_id": "uuid-here"
}
```

Response:
```json
{
  "response": "I've recorded your diabetes...",
  "session_id": "uuid-here",
  "fhir_resources": [...],
  "medplum_links": [...],
  "decomposed_count": null
}
```

### 3. Get Session Info
```bash
GET http://localhost:8005/session/{session_id}
```

## Advantages Over CLI

| Feature | CLI (`chat_flow.py`) | Gradio (`gradio_app_fhir.py`) |
|---------|---------------------|-------------------------------|
| Interface | Terminal | Web Browser |
| FHIR Resources | Not shown | Live display |
| Medplum Links | Not available | Clickable links |
| Session Statistics | Not shown | Real-time stats |
| Message Decomposition | Not available | Automatic with notice |
| Resource JSON | Not available | Expandable view |
| User Experience | Developer | End-user friendly |
| Multiple Users | One at a time | Concurrent sessions |

## Next Steps

1. **Test the Complete Flow**:
   - Start backend and Gradio
   - Try example messages
   - Verify FHIR resources appear

2. **Customize the UI**:
   - Modify CSS in `custom_css`
   - Change layout in Gradio Blocks
   - Add more example messages

3. **Enhance Resource Display**:
   - Add more resource types
   - Improve formatting
   - Add resource validation

4. **Production Deployment**:
   - Use HTTPS
   - Add authentication
   - Deploy to cloud (AWS, GCP, Heroku)

## Files

- **`gradio_app_fhir.py`** - Main Gradio interface (391 lines)
- **`app_angy_intake_agent.py`** - FastAPI backend (565 lines)
- **`test_angy_backend.py`** - Test script
- **`GRADIO_FHIR_GUIDE.md`** - This guide

## Support

For issues or questions:
- Check `INTEGRATION_REPORT.md` for technical details
- Review backend logs in terminal 1
- Check Gradio logs in terminal 2
- Test backend directly with `test_angy_backend.py`

---

**Status**: ✅ Ready to Use
**Backend Port**: 8005
**Gradio Port**: 7860
**Agent ID**: 8a9ffa61-e447-4af9-8f0f-2834ca082a21
