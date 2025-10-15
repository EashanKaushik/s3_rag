"""Example usage of HostAgent with AWS Bedrock remote agents."""

import asyncio
import logging
import sys
from uuid import uuid4
from urllib.parse import quote

from utils import get_aws_info, get_ssm_parameter
from bedrock_agentcore.identity.auth import requires_access_token
from host_agent import HostAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Agent configuration
MONITOR_AGENT_ID = "hosted_agent_monitor-YvZHocEi2B"
OPS_AGENT_ID = "hosted_agent_kcnw3-OCRp8Z8CcN"

# Get AWS info and provider names at module level
account_id, region = get_aws_info()
monitor_provider_name = get_ssm_parameter("/monitoragent/agentcore/provider-name")
ops_provider_name = get_ssm_parameter("/opsagent/agentcore/provider-name")

# Construct ARNs
monitor_agent_arn = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{MONITOR_AGENT_ID}"
)
ops_agent_arn = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{OPS_AGENT_ID}"
)

# Construct runtime URLs
monitor_runtime_url = (
    f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
    f"{quote(monitor_agent_arn, safe='')}/invocations"
)
ops_runtime_url = (
    f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
    f"{quote(ops_agent_arn, safe='')}/invocations"
)


@requires_access_token(
    provider_name=monitor_provider_name,
    scopes=[],
    auth_flow="M2M",
    into="bearer_token",
    force_authentication=True,
)
async def get_monitor_token(bearer_token: str = "") -> str:
    """Get bearer token for monitoring agent.

    Args:
        bearer_token: Injected by decorator

    Returns:
        Bearer token string
    """
    return bearer_token


@requires_access_token(
    provider_name=ops_provider_name,
    scopes=[],
    auth_flow="M2M",
    into="bearer_token",
    force_authentication=True,
)
async def get_ops_token(bearer_token: str = "") -> str:
    """Get bearer token for ops agent.

    Args:
        bearer_token: Injected by decorator

    Returns:
        Bearer token string
    """
    return bearer_token


async def main():
    """Main entry point for host agent."""
    # Fetch bearer tokens using decorator approach
    logger.info("Fetching OAuth tokens...")
    monitor_token = await get_monitor_token()
    ops_token = await get_ops_token()

    # Build agent configurations
    agent_configs = [
        {
            "name": "monitoring_agent",
            "runtime_url": monitor_runtime_url,
            "bearer_token": monitor_token,
        },
        {
            "name": "ops_agent",
            "runtime_url": ops_runtime_url,
            "bearer_token": ops_token,
        },
    ]

    # Generate session ID
    session_id = str(uuid4())
    logger.info(f"Starting host agent with session ID: {session_id}")

    # Create host agent
    host = HostAgent(
        session_id=session_id,
        user_id="ActorID",
    )

    # Register remote agents
    logger.info("Registering remote agents...")
    await host.register_agents(agent_configs)

    # Create ADK agent
    logger.info("Creating Google ADK agent...")
    host.create_agent()

    # Run interactive session
    await host.run_interactive()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    except Exception as e:
        logger.error(f"Error running host agent: {e}", exc_info=True)
        sys.exit(1)
