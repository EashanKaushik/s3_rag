import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from agent import _call_agent_stream, create_agent

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

    async def _execute_streaming(
        self, agent, user_message: str, updater: TaskUpdater, task_id: str
    ) -> None:
        """Execute agent with streaming and update task status incrementally."""
        accumulated_text = ""
        final_output = ""

        try:
            async for stream_event in _call_agent_stream(agent, user_message):
                # Check if task was cancelled
                if not self._active_tasks.get(task_id, False):
                    logger.info(f"Task {task_id} was cancelled during streaming")
                    return

                # Handle error events
                if "error" in stream_event:
                    error_msg = stream_event["error"]
                    logger.error(f"Error in stream: {error_msg}")
                    raise Exception(error_msg)

                # Handle streaming events
                if "event" in stream_event:
                    event = stream_event["event"]
                    logger.debug(f"Stream event type: {type(event).__name__}")

                    # Handle text deltas from the agent
                    if hasattr(event, "delta") and hasattr(event.delta, "text"):
                        text_chunk = event.delta.text
                        if text_chunk:
                            accumulated_text += text_chunk
                            # Send incremental update
                            await updater.update_status(
                                TaskState.working,
                                new_agent_text_message(
                                    accumulated_text, updater.context_id, updater.task_id
                                ),
                            )

                    # Handle final result
                    elif hasattr(event, "final_output"):
                        final_output = event.final_output
                        logger.info(f"Got final output: {final_output[:200]}...")

                    # Handle run completion
                    elif hasattr(event, "output"):
                        final_output = event.output
                        logger.info(f"Got output: {final_output[:200]}...")

            # Use final_output if available, otherwise use accumulated_text
            output_text = final_output or accumulated_text

            # Add final result as artifact
            if output_text:
                await updater.add_artifact(
                    [Part(root=TextPart(text=output_text))],
                    name="search_result",
                )

            await updater.complete()

        except Exception as e:
            logger.error(f"Error in streaming execution: {e}", exc_info=True)
            raise

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

            # Stream the agent response
            logger.info("Calling agent with streaming...")
            await self._execute_streaming(agent, user_message, updater, task_id)

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
