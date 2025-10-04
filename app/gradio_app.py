"""Gradio interface for the Angy intake flow."""

from __future__ import annotations

from typing import List, Tuple

import gradio as gr

from intake_conversation import IntakeConversation


def build_interface() -> gr.Blocks:
    """Construct the Gradio Blocks interface."""

    conversation = IntakeConversation()
    greeting = conversation.initial_prompt()

    def respond(message: str, history: List[Tuple[str, str]]) -> str:
        if not history:
            # Prime the transcript with the greeting for the first exchange
            history.append(("", greeting))
        return conversation.handle_message(message)

    with gr.Blocks(title="Angy Clinical Intake Assistant") as demo:
        gr.Markdown("## 🏥 Angy Clinical Intake Assistant")
        gr.Markdown(greeting)

        chatbot = gr.Chatbot(height=400)

        msg = gr.Textbox(label="Your message", placeholder="Type here to continue the intake...", lines=2)
        send = gr.Button("Send", variant="primary")

        def handle_submit(text: str, history: List[Tuple[str, str]]):
            if not text.strip():
                return history, ""
            reply = respond(text, history)
            history = history + [(text, reply)]
            return history, ""

        send.click(handle_submit, inputs=[msg, chatbot], outputs=[chatbot, msg])
        msg.submit(handle_submit, inputs=[msg, chatbot], outputs=[chatbot, msg])

    return demo


if __name__ == "__main__":
    ui = build_interface()
    ui.launch()

