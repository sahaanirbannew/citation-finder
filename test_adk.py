"""
test_adk.py
Program Purpose: Basic scratchpad script to debug standard google-adk workflows and test model invocation.
Input: Pre-configured prompt ("What is the weather in Tokyo?").
Output: Logs the ADK runner response to stdout.
"""
import asyncio
from typing import Optional
import logging

from google.genai import types
from google.adk import Agent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from agentic_app.config import Settings
import os

logger = logging.getLogger(__name__)

try:
    os.environ["GEMINI_API_KEY"] = Settings.from_env().gemini_api_key
except Exception as e:
    logger.error("Failed setting API key from env in test_adk")

async def main():
    def get_weather(location: str) -> str:
        """Get the current weather for a location."""
        return f"The weather in {location} is 25C and sunny."
    
    try:
        agent = Agent(
            name="weather_agent",
            model=Settings.from_env().gemini_model,
            instruction="You are a helpful weather bot.",
            tools=[get_weather]
        )
        
        session_service = InMemorySessionService()
        runner = Runner(
            app_name="test_app",
            agent=agent,
            session_service=session_service
        )
    except Exception as e:
        logger.error(f"Error initializing test ADK classes: {e}")
        return
    
    print("Running...")
    try:
        async for event in runner.run_async(
            user_id="user1",
            session_id="session1",
            new_message=types.Content(role="user", parts=[types.Part(text="What is the weather in Tokyo?")])
        ):
            if event.content and event.content.parts:
                print(f"[{event.author}] {event.content.parts[0]}")
            else:
                print(f"[{event.author}] EVENT NO CONTENT:", event)
    except Exception as e:
        logger.error(f"Error running the async stream: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Fatal error running main: {e}")
