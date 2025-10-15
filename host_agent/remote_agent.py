"""Remote agent connection management using A2A protocol."""

import logging
import traceback
from typing import Optional

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    Message,
    Task,
    TaskState,
    TransportProtocol,
)

logger = logging.getLogger(__name__)


class RemoteAgentConnection:
    """Manages connection and communication with a single remote agent.

    This class wraps the A2A Client to provide a clean interface for:
    - Discovering agent capabilities via agent cards
    - Sending messages and handling responses
    - Managing task state and terminal conditions
    """

    def __init__(
        self,
        client_factory: ClientFactory,
        agent_card: AgentCard,
    ):
        """Initialize remote agent connection.

        Args:
            client_factory: Factory for creating A2A clients
            agent_card: Agent card with capability information
        """
        self.agent_client: Client = client_factory.create(agent_card)
        self.card: AgentCard = agent_card
        self.pending_tasks: set[str] = set()

    def get_agent(self) -> AgentCard:
        """Get the agent card for this connection."""
        return self.card

    async def send_message(self, message: Message) -> Task | Message | None:
        """Send a message to the remote agent.

        This method handles both streaming and non-streaming responses:
        - Returns immediately if a Message response is received
        - Returns when a terminal task state is reached
        - Returns the last task if stream ends without terminal state

        Args:
            message: A2A Message to send

        Returns:
            Task, Message, or None depending on agent response

        Raises:
            Exception: If agent communication fails
        """
        last_task: Task | None = None

        try:
            async for event in self.agent_client.send_message(message):
                if isinstance(event, Message):
                    # Direct message response (synchronous agents)
                    logger.info(f"Received message from {self.card.name}")
                    return event

                # Event is a tuple (Task, UpdateEvent)
                if isinstance(event, tuple) and len(event) >= 1:
                    task = event[0]

                    # Track task
                    if task.id:
                        self.pending_tasks.add(task.id)

                    # Check if task reached terminal state
                    if self.is_terminal_or_interrupted(task):
                        logger.info(
                            f"Task {task.id} reached terminal state: {task.status.state}"
                        )
                        if task.id:
                            self.pending_tasks.discard(task.id)
                        return task

                    last_task = task

        except Exception as e:
            logger.error(f"Exception in send_message to {self.card.name}: {e}")
            traceback.print_exc()
            raise e

        return last_task

    def is_terminal_or_interrupted(self, task: Task) -> bool:
        """Check if task has reached a terminal state.

        Terminal states are:
        - completed: Task finished successfully
        - canceled: Task was canceled
        - failed: Task encountered an error
        - input_required: Agent needs user input
        - unknown: Indeterminate state

        Args:
            task: Task to check

        Returns:
            True if task is in terminal state
        """
        return task.status.state in [
            TaskState.completed,
            TaskState.canceled,
            TaskState.failed,
            TaskState.input_required,
            TaskState.unknown,
        ]


class RemoteAgentManager:
    """Manages multiple remote agent connections with AWS Bedrock runtime.

    This class handles:
    - Parallel agent discovery
    - A2A client factory configuration
    - Agent registration and lookup
    """

    def __init__(
        self,
        session_id: str,
        user_id: str = "ActorID",
        timeout: float = 300.0,
    ):
        """Initialize remote agent manager.

        Args:
            session_id: AWS Bedrock session ID
            user_id: User identifier for Bedrock
            timeout: HTTP timeout in seconds (default: 5 minutes)
        """
        self.session_id = session_id
        self.user_id = user_id
        self.timeout = timeout

        # Storage for agents
        self.connections: dict[str, RemoteAgentConnection] = {}
        self.cards: dict[str, AgentCard] = {}

    async def register_agent(
        self,
        name: str,
        runtime_url: str,
        bearer_token: str,
    ) -> AgentCard:
        """Discover and register a remote agent.

        Args:
            name: Agent identifier (for lookup)
            runtime_url: AWS Bedrock runtime URL
            bearer_token: OAuth bearer token

        Returns:
            Discovered AgentCard
        """
        logger.info(f"Discovering agent '{name}' at {runtime_url}")

        # Create HTTP client with Bedrock auth headers
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": self.session_id,
            "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": self.user_id,
        }

        httpx_client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
        )

        # Fetch agent card
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=runtime_url)
        agent_card = await resolver.get_agent_card()

        logger.info(f"Successfully discovered agent: {agent_card.name}")

        # Create A2A client factory
        config = ClientConfig(
            httpx_client=httpx_client,
            supported_transports=[
                TransportProtocol.jsonrpc,
                TransportProtocol.http_json,
            ],
        )
        client_factory = ClientFactory(config)

        # Create and store connection
        connection = RemoteAgentConnection(client_factory, agent_card)
        self.connections[name] = connection
        self.cards[name] = agent_card

        return agent_card

    def get_connection(self, name: str) -> Optional[RemoteAgentConnection]:
        """Get remote agent connection by name.

        Args:
            name: Agent identifier

        Returns:
            RemoteAgentConnection if found, None otherwise
        """
        return self.connections.get(name)

    def list_agents(self) -> list[dict]:
        """List all registered agents.

        Returns:
            List of agent info dictionaries with name and description
        """
        return [
            {
                "name": card.name,
                "description": card.description,
            }
            for card in self.cards.values()
        ]
