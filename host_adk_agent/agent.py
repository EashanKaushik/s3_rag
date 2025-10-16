from a2a.client import ClientConfig, ClientFactory
from a2a.types import TransportProtocol
from bedrock_agentcore.identity.auth import requires_access_token
from google.adk.agents.llm_agent import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from urllib.parse import quote
from uuid import uuid4
import httpx
import os

IS_DOCKER = os.getenv("DOCKER_CONTAINER", "0") == "1"

if IS_DOCKER:
    from utils import get_ssm_parameter, get_aws_info
else:
    from host_adk_agent.utils import get_ssm_parameter, get_aws_info


# AWS and agent configuration
account_id, region = get_aws_info()

MONITOR_AGENT_ID = get_ssm_parameter("/monitoragent/agentcore/runtime-id")
MONITOR_PROVIDER_NAME = get_ssm_parameter("/monitoragent/agentcore/provider-name")
MONITOR_AGENT_ARN = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{MONITOR_AGENT_ID}"
)

WEBSEARCH_AGENT_ID = get_ssm_parameter("/websearchagent/agentcore/runtime-id")
WEBSEARCH_PROVIDER_NAME = get_ssm_parameter("/websearchagent/agentcore/provider-name")
WEBSEARCH_AGENT_ARN = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{WEBSEARCH_AGENT_ID}"
)


def _create_client_factory(provider_name: str, agent_arn: str) -> ClientFactory:
    """Create an authenticated client factory for an agent."""

    @requires_access_token(
        provider_name=provider_name,
        scopes=[],
        auth_flow="M2M",
        into="bearer_token",
        force_authentication=True,
    )
    def _create(bearer_token: str = str()) -> ClientFactory:
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid4()),
            "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": "ActorID",
        }

        httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout=300.0), headers=headers
        )

        config = ClientConfig(
            httpx_client=httpx_client,
            streaming=False,
            supported_transports=[TransportProtocol.jsonrpc],
        )

        return ClientFactory(config=config)

    return _create()


# Create monitor agent
monitor_agent_card_url = (
    f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
    f"{quote(MONITOR_AGENT_ARN, safe='')}/invocations/.well-known/agent-card.json"
)

monitor_agent = RemoteA2aAgent(
    name="monitor_agent",
    description="Agent that handles monitoring tasks.",
    agent_card=monitor_agent_card_url,
    a2a_client_factory=_create_client_factory(MONITOR_PROVIDER_NAME, MONITOR_AGENT_ARN),
)

# Create websearch agent
websearch_agent_card_url = (
    f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
    f"{quote(WEBSEARCH_AGENT_ARN, safe='')}/invocations/.well-known/agent-card.json"
)

websearch_agent = RemoteA2aAgent(
    name="websearch_agent",
    description="Web search agent for finding AWS solutions, documentation, and best practices.",
    agent_card=websearch_agent_card_url,
    a2a_client_factory=_create_client_factory(
        WEBSEARCH_PROVIDER_NAME, WEBSEARCH_AGENT_ARN
    ),
)

# Create root agent
root_agent = Agent(
    model="gemini-2.0-flash",
    name="root_agent",
    instruction="""You are an efficient orchestration agent for AWS monitoring and operations.

Your role:
1. Break down user questions into sub-tasks and delegate appropriately
2. For monitoring tasks (metrics, logs, CloudWatch data): delegate to monitor_agent
3. For troubleshooting, solutions, and documentation searches: delegate to websearch_agent
4. Engage in multi-turn conversations to ensure all user needs are met
5. Synthesize information from sub-agents to provide comprehensive responses

Available sub-agents:
- monitor_agent: Handles AWS monitoring tasks
- websearch_agent: Web search agent for finding AWS solutions, documentation, and best practices

Focus exclusively on AWS-related monitoring and operations tasks.""",
    sub_agents=[monitor_agent, websearch_agent],
)
