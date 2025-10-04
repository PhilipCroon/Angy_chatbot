#!/usr/bin/env python3
"""
Autonomous Message Decomposition for Medical Intake Agents

Analyzes incoming messages for complexity and intelligently breaks them down
into simpler, sequential messages that agents can process without overwhelming.

Uses OpenAI GPT-4 for intelligent message splitting while preserving clinical details.
"""

import os
import re
from typing import List, Tuple
from openai import OpenAI
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

class MessageDecomposer:
    """Analyzes and decomposes complex medical messages into simpler parts"""

    def __init__(self, openai_api_key: str = None):
        """
        Initialize the message decomposer

        Args:
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("No OpenAI API key provided - decomposition will be disabled")
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key)

    def analyze_complexity(self, message: str) -> Tuple[bool, int]:
        """
        Analyze if a message is complex and needs decomposition

        Returns:
            (is_complex, estimated_item_count)
        """
        # Quick length check
        if len(message) < 50:
            return False, 1

        # Count potential complexity indicators
        complexity_score = 0
        item_count = 1

        # Conjunction patterns
        and_count = len(re.findall(r'\band\b', message, re.IGNORECASE))
        also_count = len(re.findall(r'\balso\b', message, re.IGNORECASE))
        conjunction_count = and_count + also_count

        if conjunction_count >= 2:
            complexity_score += 2
            item_count += conjunction_count

        # Medication patterns (name + dosage + frequency)
        med_pattern = r'\d+\s*mg\s+(?:once|twice|three times|daily|nightly)'
        med_count = len(re.findall(med_pattern, message, re.IGNORECASE))

        if med_count >= 2:
            complexity_score += 3
            item_count += med_count

        # Multiple conditions (diabetes, hypertension, etc)
        conditions = [
            r'\bdiabetes\b', r'\bhypertension\b', r'\bcholesterol\b',
            r'\bheart disease\b', r'\basthma\b', r'\bcopd\b',
            r'\bsmoker\b', r'\bsmoking\b'
        ]
        condition_count = sum(1 for pattern in conditions if re.search(pattern, message, re.IGNORECASE))

        if condition_count >= 2:
            complexity_score += 2
            item_count += condition_count

        # Comma-separated lists
        comma_count = message.count(',')
        if comma_count >= 3:
            complexity_score += 1
            item_count += (comma_count // 2)

        # Length with multiple sentences
        sentences = message.count('.') + message.count('?') + message.count('!')
        if len(message) > 100 and sentences >= 2:
            complexity_score += 1

        # Decision threshold
        is_complex = complexity_score >= 3

        if is_complex:
            logger.info(f"Message complexity detected: score={complexity_score}, estimated items={item_count}")

        return is_complex, max(2, item_count)

    def decompose_message(self, message: str, context: str = "medical intake") -> List[str]:
        """
        Decompose a complex message into simpler sequential messages

        Args:
            message: The complex message to break down
            context: Context for decomposition (e.g., "medical intake", "emergency assessment")

        Returns:
            List of simpler messages in logical order
        """
        if not self.client:
            logger.warning("OpenAI client not initialized - returning original message")
            return [message]

        # Check complexity first
        is_complex, estimated_items = self.analyze_complexity(message)

        if not is_complex:
            logger.info("Message is simple enough - no decomposition needed")
            return [message]

        # Use GPT-4 for intelligent decomposition
        prompt = f"""You are helping decompose complex medical messages for a conversational AI agent.

CONTEXT: This is a {context} conversation.

COMPLEX MESSAGE:
"{message}"

TASK: Break this message into 2-5 separate, simple statements that:
1. Each contain ONE piece of information
2. Preserve ALL clinical details (dosages, frequencies, timing, severity)
3. Flow in a natural, logical order
4. Use first person ("I have...", "I take...")
5. Are conversational and natural

RULES:
- Separate medications into individual statements
- Separate conditions into individual statements
- Keep related information together (e.g., medication name + dosage + frequency)
- Maintain chronology if mentioned

Return ONLY the decomposed messages, one per line, numbered.
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cheap
                messages=[
                    {"role": "system", "content": "You are a medical message decomposition expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Low temperature for consistency
                max_tokens=500
            )

            decomposed_text = response.choices[0].message.content.strip()

            # Parse the numbered lines
            lines = decomposed_text.split('\n')
            messages = []

            for line in lines:
                # Remove numbering (e.g., "1. ", "1) ", "1: ")
                clean_line = re.sub(r'^\d+[\.\):\s]+', '', line.strip())
                if clean_line:
                    messages.append(clean_line)

            if not messages:
                logger.warning("Failed to parse decomposed messages - using original")
                return [message]

            logger.info(f"Successfully decomposed into {len(messages)} messages")
            return messages

        except Exception as e:
            logger.error(f"Error decomposing message: {e}")
            return [message]

    def should_decompose(self, message: str) -> bool:
        """
        Quick check if a message should be decomposed

        Returns:
            True if message is complex enough to warrant decomposition
        """
        is_complex, _ = self.analyze_complexity(message)
        return is_complex and self.client is not None


# Singleton instance
_decomposer = None

def get_decomposer() -> MessageDecomposer:
    """Get or create the global MessageDecomposer instance"""
    global _decomposer
    if _decomposer is None:
        _decomposer = MessageDecomposer()
    return _decomposer


# Convenience functions
def analyze_message_complexity(message: str) -> Tuple[bool, int]:
    """Analyze if a message is complex"""
    decomposer = get_decomposer()
    return decomposer.analyze_complexity(message)


def decompose_if_complex(message: str, context: str = "medical intake") -> List[str]:
    """
    Decompose a message if it's complex, otherwise return as-is

    Returns:
        List of messages (single item if not complex, multiple if decomposed)
    """
    decomposer = get_decomposer()

    if decomposer.should_decompose(message):
        return decomposer.decompose_message(message, context)
    else:
        return [message]


if __name__ == "__main__":
    # Test the decomposer
    logging.basicConfig(level=logging.INFO)

    test_messages = [
        # Complex - multiple conditions and medications
        "I have a history of type 2 diabetes, high cholesterol, and I've been a smoker for 30 years. I take metformin 1000mg twice daily and atorvastatin 40mg at night.",

        # Complex - multiple medications
        "I take metformin 1000mg twice daily and lisinopril 10mg once daily",

        # Simple - should not decompose
        "I'm having severe chest pain",

        # Simple - should not decompose
        "My name is Sarah Johnson, born March 15, 1985",
    ]

    decomposer = get_decomposer()

    for i, msg in enumerate(test_messages, 1):
        print(f"\n{'='*70}")
        print(f"Test {i}: {msg[:60]}...")
        print(f"{'='*70}")

        is_complex, item_count = decomposer.analyze_complexity(msg)
        print(f"Complex: {is_complex}, Estimated items: {item_count}")

        if is_complex:
            decomposed = decomposer.decompose_message(msg)
            print(f"\nDecomposed into {len(decomposed)} messages:")
            for j, sub_msg in enumerate(decomposed, 1):
                print(f"  {j}. {sub_msg}")
        else:
            print("  → No decomposition needed")
