import os
from dotenv import load_dotenv
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
from bedrock_agentcore import BedrockAgentCoreApp

# Load environment variables from .env file
load_dotenv()

APP_NAME = "HostAgentA2A"

app = BedrockAgentCoreApp()

session_service = InMemorySessionService()


@app.entrypoint
async def call_agent(payload: dict, context):
    # Import agent creation inside entrypoint so workload identity is available
    from agent import getroot_agent

    # Recreate the root agent on each invocation to avoid event loop issues
    # This ensures fresh httpx clients with valid event loop references
    root_agent = getroot_agent()

    query = payload.get("prompt")
    if not query:
        raise KeyError("'prompt' field is required in payload")

    session_id = context.session_id

    if not session_id:
        raise Exception("Context session_id is not set")

    # actor_id = request_headers["x-amzn-bedrock-agentCore-runtime-custom-actor"]

    # if not actor_id:
    #     raise Exception("Actor id is not is not set")
    # TODO: Actor Id
    # Ensure session exists before running
    user_id = "Actor 1"

    in_memory_session = session_service.get_session_sync(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    if not in_memory_session:
        # Session doesn't exist, create it
        _ = session_service.create_session_sync(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )

    content = types.Content(role="user", parts=[types.Part(text=query)])

    # Use async run to properly maintain event loop across invocations
    async for event in runner.arun(user_id=user_id, session_id=session_id, new_message=content):
        yield event


if __name__ == "__main__":
    app.run()  # Ready to run on Bedrock AgentCore
