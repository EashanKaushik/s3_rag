from bedrock_agentcore.memory import MemoryClient
from contextlib import asynccontextmanager
from datetime import timedelta
from fastapi import FastAPI, Request, Header
from mcp.client.streamable_http import streamablehttp_client
from memory_hook import MonitoringMemoryHooks
from prompt import SYSTEM_PROMPT
from strands import Agent
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import boto3
import logging
import os
import uvicorn

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ssm = boto3.client("ssm")
agentcore_client = boto3.client("bedrock-agentcore")

MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-sonnet-4-20250514-v1:0")

MEMORY_ID = os.getenv("MEMORY_ID")
if not MEMORY_ID:
    raise RuntimeError("Missing MEMORY_ID environment variable")

GATEWAY_PROVIDER_NAME = os.getenv("GATEWAY_PROVIDER_NAME")
if not GATEWAY_PROVIDER_NAME:
    raise RuntimeError("Missing GATEWAY_PROVIDER_NAME environment variable")

AWS_REGION = os.getenv("MCP_REGION")
if not AWS_REGION:
    raise RuntimeError("Missing MCP_REGION environment variable")

# Use the complete runtime URL from environment variable, fallback to local
runtime_url = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")

logging.info(f"Runtime URL: {runtime_url}")

# Store session ID globally (or use a better state management solution)
current_session_id: Optional[str] = None
monitoring_hooks: Optional[MonitoringMemoryHooks] = None
strands_agent: Optional[Agent] = None
a2a_server: Optional[A2AServer] = None
gateway_client: Optional[MCPClient] = None
agent_identity_token: Optional[str] = None


def get_ssm_parameter(name: str, with_decryption: bool = True) -> str:
    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    return response["Parameter"]["Value"]


gateway_url: Optional[str] = get_ssm_parameter(
    "/monitoragent/agentcore/gateway/gateway_url"
)


def create_gateway_client() -> MCPClient:
    """Create and return a gateway MCP client."""

    global agent_identity_token, current_session_id

    response = agentcore_client.get_resource_oauth2_token(
        workloadIdentityToken=agent_identity_token,
        resourceCredentialProviderName=GATEWAY_PROVIDER_NAME,
        scopes=[],
        oauth2Flow="M2M",
        forceAuthentication=False,
    )

    gateway_access_token = response["accessToken"]

    print(f"Gateway Access token: {gateway_access_token}")
    return MCPClient(
        lambda: streamablehttp_client(
            url=gateway_url,
            headers={"Authorization": f"Bearer {gateway_access_token}"},
            timeout=timedelta(seconds=120),
        )
    )


client = MemoryClient(region_name=AWS_REGION)

bedrock_model = BedrockModel(
    model_id=MODEL_ID,
    region_name=AWS_REGION,
)

host, port = "0.0.0.0", 9000


# Lifespan context manager for shutdown cleanup
@asynccontextmanager
async def lifespan(app: FastAPI):
    global gateway_client

    yield

    # Shutdown: Stop gateway client if it was initialized
    logging.info("Shutting down...")
    if gateway_client:
        logging.info("Stopping gateway client...")
        gateway_client.stop()
        logging.info("Gateway client stopped successfully")


app = FastAPI(title="Monitoring Agent A2A Server", lifespan=lifespan)


# Middleware to capture session ID and initialize agent
@app.middleware("http")
async def capture_session_id(request: Request, call_next):
    global \
        current_session_id, \
        monitoring_hooks, \
        strands_agent, \
        a2a_server, \
        gateway_client, \
        agent_identity_token

    if request.headers.get("x-amzn-bedrock-agentcore-runtime-workload-accesstoken"):
        agent_identity_token = request.headers.get(
            "x-amzn-bedrock-agentcore-runtime-workload-accesstoken"
        )

        print(f"Agent Idenity token: {agent_identity_token}")

    session_id = request.headers.get("x-amzn-bedrock-agentcore-runtime-session-id")

    if session_id and not current_session_id:
        current_session_id = session_id
        logging.info(f"Captured session ID: {session_id}")

        # Initialize monitoring hooks with the captured session ID
        monitoring_hooks = MonitoringMemoryHooks(
            memory_id=MEMORY_ID,
            client=client,
            actor_id="Actor_1",  # TODO: Extract actor_id from headers or context
            session_id=current_session_id,
        )
        logging.info(f"Initialized monitoring hooks with session ID: {session_id}")

        # Initialize and start gateway client (needs request context for access token)
        gateway_tools = []
        try:
            logging.info("Starting gateway client in request context...")
            gateway_client = create_gateway_client()
            gateway_client.start()
            logging.info("Gateway client started successfully")

            # Get gateway tools from MCP client
            gateway_tools = gateway_client.list_tools_sync()
            logging.info(f"Loaded {len(gateway_tools)} tools from gateway client")
        except Exception as e:
            logging.error(f"Failed to initialize gateway client or load tools: {e}")

        # Create strands agent with hooks and gateway tools
        strands_agent = Agent(
            name="Monitoring Agent",
            description="A monitoring agent that handles CloudWatch logs, metrics, dashboards, and AWS service monitoring",
            system_prompt=SYSTEM_PROMPT,
            model=bedrock_model,
            tools=gateway_tools,
            hooks=[monitoring_hooks],
        )
        logging.info(
            f"Created Strands Agent with monitoring hooks and {len(gateway_tools)} tools"
        )

        # Create A2A server with the initialized agent
        a2a_server = A2AServer(
            agent=strands_agent,
            http_url=runtime_url,
            serve_at_root=True,
            host=host,
            port=port,
            version="1.0.0",
        )
        logging.info("Created A2A Server")

    response = await call_next(request)
    return response


@app.get("/ping")
def ping(
    x_amzn_bedrock_agentcore_runtime_session_id: Optional[str] = Header(
        None, alias="X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
    ),
):
    return {
        "status": "healthy",
        "agent": "monitoring_agent",
        "session_id": x_amzn_bedrock_agentcore_runtime_session_id or current_session_id,
        "runtime_url": runtime_url,
    }


# Conditional mount - only mount if a2a_server is initialized
@app.middleware("http")
async def mount_a2a_conditionally(request: Request, call_next):
    global a2a_server

    # If a2a_server exists and hasn't been mounted yet, mount it
    if a2a_server is not None and not hasattr(app, "_a2a_mounted"):
        # Mark as mounted to avoid re-mounting
        app._a2a_mounted = True
        # We can't dynamically mount here, so we need a different approach
        logging.info("A2A server ready to handle requests")

    response = await call_next(request)
    return response


# We'll handle mounting differently - check if a2a_server exists before routing
@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_to_a2a(request: Request):
    global a2a_server

    if a2a_server is None:
        return {
            "error": "Agent not initialized",
            "message": "Waiting for session ID to initialize agent",
        }

    # Forward request to a2a_server
    a2a_app = a2a_server.to_fastapi_app()
    return await a2a_app(request.scope, request.receive, request._send)


if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
