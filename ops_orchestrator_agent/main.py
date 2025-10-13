from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from agent_executor import OpsRemediationAgentExecutor
from starlette.responses import JSONResponse
import logging
import os
import uvicorn

logger = logging.getLogger(__name__)

runtime_url = os.getenv("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")

agent_card = AgentCard(
    name="Ops Remediation Agent",
    description="Operations remediation agent that provides documentation and solutions for JIRA tickets by searching AWS documentation",
    url=runtime_url,
    version="1.0.0",
    defaultInputModes=["text/plain"],
    defaultOutputModes=["text/plain"],
    capabilities=AgentCapabilities(streaming=False, pushNotifications=False),
    skills=[
        AgentSkill(
            id="ops-remediation",
            name="Operations Remediation",
            description="Search AWS documentation and provide remediation strategies for operational issues",
            tags=["operations", "remediation", "aws", "documentation"],
            examples=[
                "Find documentation for fixing high CPU usage in EC2",
                "Search for solutions to RDS connection timeout issues",
                "Get remediation steps for Lambda function errors",
            ],
        ),
        AgentSkill(
            id="jira-documentation",
            name="JIRA Documentation",
            description="Provide documentation and updates for JIRA tickets",
            tags=["jira", "documentation", "ticketing"],
            examples=[
                "Document the fix for JIRA ticket OPS-123",
                "Provide status update for incident ticket",
            ],
        ),
    ],
)

# Create request handler with executor
request_handler = DefaultRequestHandler(
    agent_executor=OpsRemediationAgentExecutor(), task_store=InMemoryTaskStore()
)

# Create A2A server
server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)

# Build the app and add health endpoint
app = server.build()


@app.route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint"""
    return JSONResponse(
        {"status": "healthy", "agent": "ops_remediation_agent", "version": "1.0.0"}
    )


@app.route("/ping", methods=["GET"])
async def ping(request):
    """Ping endpoint"""
    return JSONResponse({"message": "pong"})


logger.info("✅ A2A Server configured")
logger.info(f"📍 Server URL: {runtime_url}")
logger.info(f"🏥 Health check: {runtime_url}/health")
logger.info(f"🏓 Ping: {runtime_url}/ping")

if __name__ == "__main__":
    # Run the server
    host, port = "0.0.0.0", 9000

    uvicorn.run(app, host=host, port=port)
