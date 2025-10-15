import argparse
import asyncio
import json
import logging
from uuid import uuid4
from urllib.parse import quote

import httpx
import requests
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from bedrock_agentcore.identity.auth import requires_access_token

from utils import get_ssm_parameter, get_aws_info

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # set request timeout to 5 minutes

# Get AWS region and account ID dynamically
account_id, region = get_aws_info()

moniter_agent_id = get_ssm_parameter("/monitoragent/agentcore/runtime-id")
websearch_agent_id = "hosted_agent_kcnw3-OCRp8Z8CcN"

moniter_provider_name = get_ssm_parameter("/monitoragent/agentcore/provider-name")
moniter_agent_arn = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{moniter_agent_id}"
)

# websearch_provider_name = get_ssm_parameter("/websearchagent/agentcore/provider-name")
# websearch_agent_arn = (
#     f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{websearch_agent_id}"
# )


def create_message(*, role: Role = Role.user, text: str) -> Message:
    """Create a message for A2A protocol."""
    return Message(
        kind="message",
        role=role,
        parts=[Part(TextPart(kind="text", text=text))],
        message_id=uuid4().hex,
    )


def fetch_agent_card(provider_name: str, agent_arn: str):
    """Fetch agent card from the runtime endpoint."""

    @requires_access_token(
        provider_name=provider_name,
        scopes=[],
        auth_flow="M2M",
        into="bearer_token",
        force_authentication=True,
    )
    def _fetch_with_auth(bearer_token: str = str()):
        # URL encode the agent ARN
        escaped_agent_arn = quote(agent_arn, safe="")

        # Construct the URL
        url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped_agent_arn}/invocations/.well-known/agent-card.json"

        # Generate a unique session ID
        session_id = str(uuid4())
        logger.info(f"Fetching agent card with session ID: {session_id}")

        # Set headers
        headers = {
            "Accept": "*/*",
            "Authorization": f"Bearer {bearer_token}",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        }

        try:
            # Make the request
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            # Parse and return agent card
            agent_card = response.json()
            logger.info("Agent card fetched successfully")
            logger.info(json.dumps(agent_card, indent=2))
            return agent_card

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching agent card: {e}")
            return None

    return _fetch_with_auth()


async def send_message(
    message: str, session_id: str, provider_name: str, agent_arn: str
):
    """Send a message to the agent using A2A protocol."""

    @requires_access_token(
        provider_name=provider_name,
        scopes=[],
        auth_flow="M2M",
        into="bearer_token",
        force_authentication=True,
    )
    async def _send_with_auth(bearer_token: str = str()):
        # Construct runtime URL
        escaped_agent_arn = quote(agent_arn, safe="")
        runtime_url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{escaped_agent_arn}/invocations"

        # Add authentication headers
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
            "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": "ActorID",
        }

        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers=headers
        ) as httpx_client:
            # Get agent card from the runtime URL
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=runtime_url)
            agent_card = await resolver.get_agent_card()

            # Create client using factory
            config = ClientConfig(
                httpx_client=httpx_client,
                streaming=False,  # Use non-streaming mode for sync response
            )
            factory = ClientFactory(config)
            client = factory.create(agent_card)

            # Create and send message
            msg = create_message(text=message)

            # With streaming=False, this will yield exactly one result
            async for event in client.send_message(msg):
                if isinstance(event, Message):
                    logger.info("Received message response")
                    logger.info(event.model_dump_json(exclude_none=True, indent=2))

                    # Extract and print text content
                    print("\n🤖 Assistant: ", end="", flush=True)
                    for part in event.parts:
                        if hasattr(part, "text"):
                            print(part.text, flush=True)

                    return event
                elif isinstance(event, tuple) and len(event) == 2:
                    # (Task, UpdateEvent) tuple
                    task, update_event = event
                    logger.info(
                        f"Task: {task.model_dump_json(exclude_none=True, indent=2)}"
                    )
                    if update_event:
                        logger.info(
                            f"Update: {update_event.model_dump_json(exclude_none=True, indent=2)}"
                        )
                    return task
                else:
                    # Fallback for other response types
                    logger.info(f"Response: {str(event)}")
                    return event

    return await _send_with_auth()


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Connect to a Bedrock agent")
    parser.add_argument(
        "--agent",
        choices=["monitor", "websearch"],
        required=True,
        help="Agent to connect to: 'monitor' or 'websearch'",
    )
    args = parser.parse_args()

    # Set variables based on agent choice
    if args.agent == "monitor":
        selected_provider_name = moniter_provider_name
        selected_agent_arn = moniter_agent_arn
        print(f"\n🔍 Using Monitor Agent (ID: {moniter_agent_id})")
    else:  # websearch
        selected_provider_name = websearch_provider_name
        selected_agent_arn = websearch_agent_arn
        print(f"\n🔍 Using WebSearch Agent (ID: {websearch_agent_id})")

    # First, fetch and display the agent card
    print("\n📋 Fetching agent card...\n")
    card = fetch_agent_card(selected_provider_name, selected_agent_arn)

    if not card:
        print("❌ Failed to fetch agent card. Exiting.")
        exit(1)

    # Start interactive session
    session_id = str(uuid4())
    print(f"\n🤖 Starting interactive session (Session ID: {session_id})")
    print("Type 'q' or 'quit' to exit.\n")

    while True:
        user_input = input("👤 You: ").strip()

        if user_input.lower() in ["q", "quit"]:
            print("👋 Goodbye!")
            break

        if not user_input:
            continue

        # Send message using async A2A protocol
        asyncio.run(
            send_message(
                user_input, session_id, selected_provider_name, selected_agent_arn
            )
        )
        print()
