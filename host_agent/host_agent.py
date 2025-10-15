"""Host agent for orchestrating multiple remote agents using Google ADK."""

import asyncio
import json
import logging
import os
from typing import Optional
from uuid import uuid4

from a2a.types import Message, Part, Role, Task, TaskState, TextPart
from google.adk import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.tool_context import ToolContext

from remote_agent import RemoteAgentConnection, RemoteAgentManager

logger = logging.getLogger(__name__)


class HostAgent:
    """Host agent that orchestrates multiple remote agents.

    This agent uses an LLM to intelligently delegate user requests to
    specialized remote agents based on their capabilities. It maintains
    conversation state and coordinates multi-agent interactions.

    Key responsibilities:
    - Agent discovery and registration
    - Request delegation to appropriate agents
    - State management across conversations
    - Response aggregation and formatting
    """

    def __init__(
        self,
        session_id: str,
        user_id: str = "ActorID",
        model: str | None = None,
    ):
        """Initialize the host agent.

        Args:
            session_id: AWS Bedrock session ID
            user_id: User identifier for Bedrock
            model: LiteLLM model name (default: gemini-2.0-flash-001)
        """
        self.session_id = session_id
        self.user_id = user_id
        self.model_name = model or os.getenv(
            "LITELLM_MODEL", "gemini/gemini-2.0-flash-001"
        )

        # Remote agent manager
        self.agent_manager = RemoteAgentManager(
            session_id=session_id,
            user_id=user_id,
        )

        # Cached agent list string for LLM instructions
        self._agents_list: str = ""

        # Google ADK agent (created after agent registration)
        self._adk_agent: Optional[Agent] = None

    async def register_agents(
        self,
        agents: list[dict[str, str]],
    ) -> None:
        """Register multiple remote agents in parallel.

        Args:
            agents: List of agent configs with keys:
                - name: Agent identifier
                - runtime_url: AWS Bedrock runtime URL
                - bearer_token: OAuth bearer token
        """
        logger.info(f"Registering {len(agents)} remote agents...")

        async with asyncio.TaskGroup() as task_group:
            for agent_config in agents:
                task_group.create_task(
                    self.agent_manager.register_agent(
                        name=agent_config["name"],
                        runtime_url=agent_config["runtime_url"],
                        bearer_token=agent_config["bearer_token"],
                    )
                )

        # Update cached agent list
        self._update_agents_list()
        logger.info("All agents registered successfully")

    def _update_agents_list(self) -> None:
        """Update the cached agent list string for LLM instructions."""
        agent_info = []
        for agent in self.agent_manager.list_agents():
            agent_info.append(json.dumps(agent))
        self._agents_list = "\n".join(agent_info)

    def create_agent(self) -> Agent:
        """Create the Google ADK agent with tools for agent orchestration.

        Returns:
            Configured ADK Agent
        """
        self._adk_agent = Agent(
            model=LiteLlm(model=self.model_name),
            name="host_agent",
            instruction=self._root_instruction,
            before_model_callback=self._before_model_callback,
            description=(
                "This agent orchestrates the decomposition of user requests into "
                "tasks that can be performed by specialized child agents."
            ),
            tools=[
                self.list_remote_agents,
                self.send_message,
            ],
        )
        return self._adk_agent

    def _root_instruction(self, context: ReadonlyContext) -> str:
        """Generate dynamic instructions for the LLM based on current state.

        Args:
            context: Read-only context with conversation state

        Returns:
            Instruction string for the LLM
        """
        current_agent = self._check_state(context)

        return f"""You are an expert delegator that can delegate user requests to the
appropriate remote agents.

Discovery:
- Use `list_remote_agents` to list the available remote agents you can use to delegate tasks.

Execution:
- For actionable requests, use `send_message` to interact with remote agents to take action.
- Always include the remote agent name when responding to the user.

Guidelines:
- Rely on tools to address requests; don't make up responses.
- If unsure, ask the user for more details.
- Focus on the most recent parts of the conversation.

Available Agents:
{self._agents_list}

Current Active Agent: {current_agent['active_agent']}
"""

    def _check_state(self, context: ReadonlyContext) -> dict:
        """Check conversation state for active agent.

        Args:
            context: Read-only context

        Returns:
            Dictionary with active_agent information
        """
        state = context.state
        if (
            "context_id" in state
            and "session_active" in state
            and state["session_active"]
            and "agent" in state
        ):
            return {"active_agent": f'{state["agent"]}'}
        return {"active_agent": "None"}

    def _before_model_callback(
        self,
        callback_context: CallbackContext,
        llm_request,
    ):
        """Initialize session state before LLM call.

        Args:
            callback_context: Callback context with mutable state
            llm_request: LLM request object
        """
        state = callback_context.state
        if "session_active" not in state or not state["session_active"]:
            state["session_active"] = True

    def list_remote_agents(self) -> list[dict]:
        """List available remote agents for task delegation.

        Returns:
            List of agent info with name and description
        """
        agents = self.agent_manager.list_agents()
        logger.info(f"Listed {len(agents)} remote agents")
        return agents

    async def send_message(
        self,
        agent_name: str,
        message: str,
        tool_context: ToolContext,
    ) -> list[str]:
        """Send a message to a remote agent and handle the response.

        This method:
        1. Validates agent exists
        2. Manages conversation state (context_id, task_id, message_id)
        3. Sends message via A2A protocol
        4. Handles different response types (Message vs Task)
        5. Updates state based on task status
        6. Escalates to user when needed

        Args:
            agent_name: Name of the remote agent
            message: Message text to send
            tool_context: ADK tool context for state management

        Returns:
            List of response strings from the agent

        Raises:
            ValueError: If agent not found or task fails
        """
        # Validate agent exists
        connection = self.agent_manager.get_connection(agent_name)
        if not connection:
            raise ValueError(
                f"Agent '{agent_name}' not found. "
                f"Available agents: {[a['name'] for a in self.agent_manager.list_agents()]}"
            )

        # Get or initialize state
        state = tool_context.state

        # Check if we're switching agents
        previous_agent = state.get("agent")
        if previous_agent and previous_agent != agent_name:
            # Switching to a different agent - clear task_id but keep context_id
            # Each agent has its own task space, but context_id can span agents
            logger.info(f"Switching from {previous_agent} to {agent_name}, clearing task_id")
            state.pop("task_id", None)

        state["agent"] = agent_name

        context_id = state.get("context_id")
        task_id = state.get("task_id")
        message_id = state.get("message_id", str(uuid4()))

        logger.info(
            f"Sending message to {agent_name} "
            f"(context_id={context_id}, task_id={task_id})"
        )

        # Create A2A message
        request_message = Message(
            role=Role.user,
            parts=[Part(root=TextPart(text=message))],
            message_id=message_id,
            context_id=context_id,
            task_id=task_id,
        )

        # Send message and get response
        response = await connection.send_message(request_message)

        # Handle Message response (synchronous agents)
        if isinstance(response, Message):
            logger.info(f"Received synchronous message from {agent_name}")
            return self._extract_text_from_parts(response.parts)

        # Handle Task response (asynchronous agents)
        if not isinstance(response, Task):
            logger.warning(f"Unexpected response type from {agent_name}: {type(response)}")
            return [f"Received unexpected response from {agent_name}"]

        task: Task = response

        # Update session state
        state["session_active"] = task.status.state not in [
            TaskState.completed,
            TaskState.canceled,
            TaskState.failed,
            TaskState.unknown,
        ]

        if task.context_id:
            state["context_id"] = task.context_id

        if task.id:
            state["task_id"] = task.id

        # Handle different task states
        if task.status.state == TaskState.input_required:
            logger.info(f"Task {task.id} requires user input")
            tool_context.actions.skip_summarization = True
            tool_context.actions.escalate = True

        elif task.status.state == TaskState.canceled:
            raise ValueError(f"Agent {agent_name} task {task.id} was canceled")

        elif task.status.state == TaskState.failed:
            error_msg = f"Agent {agent_name} task {task.id} failed"
            if task.status.message:
                error_msg += f": {self._extract_text_from_parts(task.status.message.parts)}"
            raise ValueError(error_msg)

        # Extract response content
        response_parts = []

        if task.status.message:
            response_parts.extend(
                self._extract_text_from_parts(task.status.message.parts)
            )

        if task.artifacts:
            for artifact in task.artifacts:
                response_parts.extend(
                    self._extract_text_from_parts(artifact.parts)
                )

        logger.info(f"Successfully received response from {agent_name}")
        return response_parts

    def _extract_text_from_parts(self, parts: list[Part]) -> list[str]:
        """Extract text content from A2A message parts.

        Args:
            parts: List of A2A message parts

        Returns:
            List of text strings
        """
        text_parts = []
        for part in parts:
            if hasattr(part.root, "text"):
                text_parts.append(part.root.text)
            elif hasattr(part.root, "kind") and part.root.kind == "text":
                text_parts.append(part.root.text)
            else:
                # Handle other part types (data, file, etc.)
                text_parts.append(f"[{part.root.kind}]")
        return text_parts

    async def run_interactive(self):
        """Run an interactive session with the host agent.

        This method creates a simple REPL for testing agent interactions.
        For simplicity, this directly routes messages to agents without LLM orchestration.
        """
        print(f"\n> Host Agent Interactive Session")
        print(f"Session ID: {self.session_id}")
        print(f"Registered agents: {len(self.agent_manager.list_agents())}")
        print("\nAvailable commands:")
        print("  list - List available agents")
        print("  <agent_name>: <message> - Send message to specific agent")
        print("  quit - Exit")
        print()

        # Simple state for tracking conversation
        state = {}

        while True:
            user_input = input("You: ").strip()

            if user_input.lower() in ["q", "quit", "exit"]:
                print("Goodbye!")
                break

            if not user_input:
                continue

            try:
                # Handle special commands
                if user_input.lower() == "list":
                    agents = self.list_remote_agents()
                    print("\nAvailable agents:")
                    for agent in agents:
                        print(f"  - {agent['name']}: {agent['description']}")
                    print()
                    continue

                # Parse agent_name: message format
                if ":" in user_input:
                    agent_name, message = user_input.split(":", 1)
                    agent_name = agent_name.strip()
                    message = message.strip()

                    # Create a simple tool context mock
                    from google.adk.tools.tool_context import ToolContext
                    from google.adk.events.event import Event
                    from google.genai import types as genai_types

                    # Create a minimal context
                    class SimpleToolContext:
                        def __init__(self):
                            self.state = state
                            self.actions = type('Actions', (), {
                                'skip_summarization': False,
                                'escalate': False
                            })()

                    tool_context = SimpleToolContext()

                    print(f"\nSending to {agent_name}...", flush=True)

                    # Call send_message directly
                    response = await self.send_message(agent_name, message, tool_context)

                    print(f"\n{agent_name} response:")
                    for part in response:
                        print(part)
                    print()

                else:
                    print("\nPlease use format: <agent_name>: <message>")
                    print("Or type 'list' to see available agents\n")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                print(f"\nError: {e}\n")

