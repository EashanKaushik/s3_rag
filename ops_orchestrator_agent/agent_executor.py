from a2a.server.agent_execution.agent_executor import AgentExecutor
import logging
from agent import _call_agent, create_agent
from a2a.server.events.event_queue import EventQueue
from a2a.server.agent_execution.context import RequestContext
import datetime

logger = logging.getLogger(__name__)

# SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
# ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-User-Id"


class OpsRemediationAgentExecutor(AgentExecutor):
    """
    Agent executor that wraps the OpenAI-based ops remediation agent
    for A2A server compatibility
    """

    def __init__(self):
        """Initialize the executor"""
        self._agent = None
        self._active_tasks = {}
        logger.info("OpsRemediationAgentExecutor initialized")

    async def _get_agent(self, session_id: str, actor_id: str):
        """Lazily initialize and return the agent"""
        if self._agent is None:
            logger.info("Creating lead orchestrator agent...")
            self._agent = create_agent(session_id=session_id, actor_id=actor_id)
            logger.info("Lead orchestrator agent created successfully")
        return self._agent

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Execute the agent's logic for a given request context.
        """
        if context.call_context:
            headers = context.call_context.state.get("headers", {})
            session_id = headers.get("x-amzn-bedrock-agentcore-runtime-session-id")
            # actor_id = headers.get("x-amzn-bedrock-agentcore-runtime-user-id")

        if not session_id:
            raise RuntimeError("Session ID is not set")

        # if not actor_id:
        #     raise RuntimeError("Actor ID is not set")
        try:
            task_id = context.task_id
            logger.info(f"Executing task {task_id}")

            # Extract the user message from context
            user_message = ""

            if context.message and context.message.parts:
                for part in context.message.parts:
                    # A2A protocol wraps TextPart in a Part container with 'root' attribute
                    if hasattr(part, "root") and hasattr(part.root, "text"):
                        user_message += part.root.text
                    # Fallback: direct text attribute
                    elif hasattr(part, "text"):
                        user_message += part.text
                    # Fallback: dict access
                    elif isinstance(part, dict) and "text" in part:
                        user_message += part["text"]

            logger.info(f"📝 User message extracted: '{user_message}'")

            # Get the agent instance
            # TODO: Actor
            agent = await self._get_agent(session_id=session_id, actor_id="Actor1")

            # Mark task as active
            self._active_tasks[task_id] = True

            # Call the agent
            logger.info("Calling agent with user message...")
            result = await _call_agent(agent, user_message)

            # Check if task was cancelled
            if not self._active_tasks.get(task_id, False):
                logger.info(f"Task {task_id} was cancelled")
                return

            # Publish completion event
            from a2a.types import (
                TaskStatusUpdateEvent,
                TaskState,
                TaskStatus,
                Message,
                TextPart,
                Role,
            )
            import uuid

            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    context_id=context.context_id,
                    task_id=task_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.completed,
                        message=Message(
                            messageId=str(uuid.uuid4()),
                            role=Role.user,  # Use Role.user
                            parts=[TextPart(text=result.get("output", ""))],
                        ),
                        timestamp=datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                    ),
                )
            )

            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)

            # Publish failure event
            from a2a.types import (
                TaskStatusUpdateEvent,
                TaskState,
                TaskStatus,
                Message,
                TextPart,
                Role,
            )
            import uuid

            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    context_id=context.context_id,
                    task_id=task_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=Message(
                            messageId=str(uuid.uuid4()),
                            role=Role.user,  # Use Role.user
                            parts=[TextPart(text=str(e))],
                        ),
                        timestamp=datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                    ),
                )
            )
        finally:
            # Clean up task from active tasks
            self._active_tasks.pop(task_id, None)

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Request the agent to cancel an ongoing task.
        """
        try:
            task_id = context.task_id
            logger.info(f"Cancelling task {task_id}")

            # Mark task as cancelled
            self._active_tasks[task_id] = False

            # Publish cancellation event
            from a2a.types import (
                TaskStatusUpdateEvent,
                TaskState,
                TaskStatus,
                Message,
                TextPart,
                Role,
            )
            import uuid

            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    context_id=context.context_id,
                    task_id=task_id,
                    final=True,
                    status=TaskStatus(
                        state=TaskState.canceled,
                        message=Message(
                            messageId=str(uuid.uuid4()),
                            role=Role.user,  # Use Role.user
                            parts=[TextPart(text="Task cancelled by user")],
                        ),
                        timestamp=datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                    ),
                )
            )

            logger.info(f"Task {task_id} cancelled successfully")

        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
