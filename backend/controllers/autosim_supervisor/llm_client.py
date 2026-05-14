import os
from dotenv import load_dotenv
from groq import Groq
from langchain_groq import ChatGroq
import google.generativeai as genai

# Load your .env file
load_dotenv()


class GroqClient:
    """Ultra-low latency client, perfect for real-time robotics."""

    def __init__(self, model="openai/gpt-oss-120b"):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in .env")

        self.client = Groq(api_key=api_key)
        self.model = model

    def generate(self, prompt):
        # Groq natively supports JSON mode!
        chat_completion = self.client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are an autonomous robotics director. Always return valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            temperature=0.0,  # Keep it deterministic for robotics!
            response_format={"type": "json_object"},
        )
        return chat_completion.choices[0].message.content


class GeminiClient:
    """Great for heavy spatial reasoning and complex tasks."""

    def __init__(self, model="gemini-1.5-pro"):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env")

        genai.configure(api_key=api_key)
        # We enforce JSON response schema here too
        self.model = genai.GenerativeModel(
            model_name=model,
            generation_config={"response_mime_type": "application/json"},
        )

    def generate(self, prompt):
        response = self.model.generate_content(prompt)
        return response.text
