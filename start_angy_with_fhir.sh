#!/bin/bash

# Wait for TCP port to become available (defaults to 15 seconds)
wait_for_port() {
    local port=$1
    local retries=${2:-15}
    local delay=${3:-1}
    for ((i=0; i<retries; i++)); do
        if lsof -ti:"$port" > /dev/null 2>&1; then
            return 0
        fi
        sleep "$delay"
    done
    return 1
}

# Angy Chatbot with FHIR Integration - Startup Script
# This script starts both the backend and Gradio interface

echo "================================================================================"
echo "  Starting Angy Chatbot with FHIR Integration"
echo "================================================================================"
echo ""

# Change to script directory
cd "$(dirname "$0")"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "   Please create .env file with your credentials"
    echo "   See .env.example for template"
    exit 1
fi

# Source environment variables
export $(cat .env | grep -v '^#' | xargs)

echo "✅ Environment variables loaded"
echo ""

# Check if backend is already running
if lsof -ti:8005 > /dev/null 2>&1; then
    echo "⚠️  Backend already running on port 8005"
    echo "   Killing existing process..."
    lsof -ti:8005 | xargs kill
    sleep 2
fi

# Check if Gradio is already running
if lsof -ti:7860 > /dev/null 2>&1; then
    echo "⚠️  Gradio already running on port 7860"
    echo "   Killing existing process..."
    lsof -ti:7860 | xargs kill
    sleep 2
fi

echo "Starting services..."
echo ""

# Start backend in background
echo "📡 Starting FastAPI Backend (port 8005)..."
python app_angy_intake_agent.py > backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to start responding (up to ~20s)
if ! wait_for_port 8005 20; then
    echo "❌ Backend failed to start"
    echo "   Check backend.log for errors"
    exit 1
fi

echo "✅ Backend running (PID: $BACKEND_PID)"
echo "   URL: http://localhost:8005"
echo "   Logs: backend.log"
echo ""

# Start Gradio in background
echo "🌐 Starting Gradio Interface (port 7860)..."
python gradio_app_fhir.py > gradio.log 2>&1 &
GRADIO_PID=$!

# Wait for Gradio to start responding (up to ~30s)
if ! wait_for_port 7860 30; then
    echo "❌ Gradio failed to start"
    echo "   Check gradio.log for errors"
    # Kill backend
    kill $BACKEND_PID
    exit 1
fi

echo "✅ Gradio running (PID: $GRADIO_PID)"
echo "   URL: http://localhost:7860"
echo "   Logs: gradio.log"
echo ""

echo "================================================================================"
echo "  🎉 All services started successfully!"
echo "================================================================================"
echo ""
echo "📱 Open your browser to: http://localhost:7860"
echo ""
echo "Backend API: http://localhost:8005"
echo "Backend Health: http://localhost:8005/health"
echo ""
echo "To stop services:"
echo "  kill $BACKEND_PID $GRADIO_PID"
echo ""
echo "Or run:"
echo "  lsof -ti:8005 | xargs kill && lsof -ti:7860 | xargs kill"
echo ""
echo "Logs:"
echo "  Backend: tail -f backend.log"
echo "  Gradio:  tail -f gradio.log"
echo ""
echo "================================================================================"
echo ""

# Save PIDs to file for easy stopping
echo "$BACKEND_PID" > .backend.pid
echo "$GRADIO_PID" > .gradio.pid

echo "PIDs saved to .backend.pid and .gradio.pid"
echo ""

# Wait for user to press Ctrl+C
echo "Press Ctrl+C to stop all services..."
echo ""

# Trap Ctrl+C and cleanup
trap "echo ''; echo 'Stopping services...'; kill $BACKEND_PID $GRADIO_PID 2>/dev/null; rm -f .backend.pid .gradio.pid; echo 'Services stopped.'; exit 0" INT

# Keep script running
wait
