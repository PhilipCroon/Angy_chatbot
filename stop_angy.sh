#!/bin/bash

# Stop Angy Chatbot Services

echo "Stopping Angy services..."

# Stop by PID files if they exist
if [ -f .backend.pid ]; then
    BACKEND_PID=$(cat .backend.pid)
    if kill -0 $BACKEND_PID 2>/dev/null; then
        kill $BACKEND_PID
        echo "✅ Stopped backend (PID: $BACKEND_PID)"
    fi
    rm -f .backend.pid
fi

if [ -f .gradio.pid ]; then
    GRADIO_PID=$(cat .gradio.pid)
    if kill -0 $GRADIO_PID 2>/dev/null; then
        kill $GRADIO_PID
        echo "✅ Stopped Gradio (PID: $GRADIO_PID)"
    fi
    rm -f .gradio.pid
fi

# Stop by port
if lsof -ti:8005 > /dev/null 2>&1; then
    lsof -ti:8005 | xargs kill
    echo "✅ Stopped process on port 8005"
fi

if lsof -ti:7860 > /dev/null 2>&1; then
    lsof -ti:7860 | xargs kill
    echo "✅ Stopped process on port 7860"
fi

echo "All services stopped."
