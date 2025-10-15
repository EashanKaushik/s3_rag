import datetime
import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Message,
    Part,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from agent import _call_agent, create_agent

logger = logging.getLogger(__name__)


class WebSearchAgentExecutor(AgentExecutor):
    """
    Agent executor that wraps the OpenAI-based web search agent
    for A2A server compatibility
    """

    def __init__(self):
        """Initialize the executor"""
        self._agent = None
        self._active_tasks = {}
        logger.info("WebSearchAgentExecutor initialized")

    async def _get_agent(self, session_id: str, actor_id: str):
        """Lazily initialize and return the agent"""
        if self._agent is None:
            logger.info("Creating web search agent...")
            self._agent = create_agent(session_id=session_id, actor_id=actor_id)
            logger.info("Web search agent created successfully")
        return self._agent

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Execute the agent's logic for a given request context.
        """
        # Extract session and actor IDs from headers
        session_id = None
        # TODO: Remove Actor Id
        actor_id = "Actor1"  # Default actor ID

        if context.call_context:
            headers = context.call_context.state.get("headers", {})
            session_id = headers.get("x-amzn-bedrock-agentcore-runtime-session-id")
            actor_id = headers.get("x-amzn-bedrock-agentcore-runtime-user-id", actor_id)

        if not session_id:
            logger.error("Session ID is not set")
            raise ServerError(error=InvalidParamsError())

        # Get or create task
        task = context.current_task
        if not task:
            logger.info("No current task, creating new task")
            task = new_task(context.message)  # type: ignore
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        task_id = context.task_id

        try:
            logger.info(f"Executing task {task.id}")

            # Extract user input
            user_message = context.get_user_input()
            if not user_message:
                logger.error("No user message found in context")
                raise ServerError(error=InvalidParamsError())

            logger.info(f"User message: '{user_message}'")

            # Get the agent instance
            agent = await self._get_agent(session_id=session_id, actor_id=actor_id)

            # Mark task as active
            self._active_tasks[task_id] = True

            # Update task to working state
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    "Processing your request...", task.context_id, task.id
                ),
            )

            # Call the agent
            logger.info("Calling agent with user message...")
            result = await _call_agent(agent, user_message)

            # Check if task was cancelled
            if not self._active_tasks.get(task_id, False):
                logger.info(f"Task {task_id} was cancelled")
                return

            # Add result as artifact and complete
            output_text = result.get("output", "")
            await updater.add_artifact(
                [Part(root=TextPart(text=output_text))],
                name="search_result",
            )
            await updater.complete()

            logger.info(f"Task {task_id} completed successfully")

        except ServerError:
            # Re-raise ServerError as-is
            raise
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
            raise ServerError(error=InternalError()) from e
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
        task_id = context.task_id
        logger.info(f"Cancelling task {task_id}")

        try:
            # Mark task as cancelled
            self._active_tasks[task_id] = False

            task = context.current_task
            if task:
                updater = TaskUpdater(event_queue, task.id, task.context_id)
                await updater.cancel()
                logger.info(f"Task {task_id} cancelled successfully")
            else:
                logger.warning(f"No task found for task_id {task_id}")

        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
            raise ServerError(error=InternalError()) from e
