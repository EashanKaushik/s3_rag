from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
from bedrock_agentcore import BedrockAgentCoreApp


APP_NAME = "HostAgentA2A"

app = BedrockAgentCoreApp()

session_service = InMemorySessionService()

root_agent = None


@app.entrypoint
async def call_agent(payload: dict, context):
    global root_agent

    from bedrock_agentcore.runtime.context import BedrockAgentCoreContext

    # Debug: Check if workload token is set
    try:
        token = BedrockAgentCoreContext.get_workload_access_token()
        app.logger.info(f"Workload token is set: {token[:20] if token else 'None'}...")
    except Exception as e:
        app.logger.error(f"Workload token not available: {e}")

    # if not root_agent:
    #     # Import agent creation inside entrypoint so workload identity is available
    #     from agent import getroot_agent

    #     # Get or create the root agent (will be created on first call)
    #     root_agent = getroot_agent()

    query = payload.get("prompt")
    if not query:
        raise KeyError("'prompt' field is required in payload")

    session_id = context.session_id

    if not session_id:
        raise Exception("Context session_id is not set")

    # actor_id = request_headers["x-amzn-bedrock-agentCore-runtime-custom-actor"]

    # if not actor_id:
    #     raise Exception("Actor id is not is not set")
    yield "Hello"
    # # TODO: Actor Id
    # session_service.create_session(
    #     app_name=APP_NAME, user_id="Actor 1", session_id=session_id
    # )
    # runner = Runner(
    #     agent=root_agent, app_name=APP_NAME, session_service=session_service
    # )

    # content = types.Content(role="user", parts=[types.Part(text=query)])
    # # TODO: Actor Id

    # events = runner.run(user_id="Actor 1", session_id=session_id, new_message=content)

    # for event in events:
    #     yield event
    #     if event.is_final_response() and event.content:
    #         final_answer = event.content.parts[0].text.strip()

    # return final_answer


if __name__ == "__main__":
    app.run()  # Ready to run on Bedrock AgentCore
