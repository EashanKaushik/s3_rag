    async def run_interactive(self):
        """Run an interactive session with the host agent.

        This method creates a simple REPL for testing agent interactions.
        """
        if not self._adk_agent:
            self.create_agent()

        # Create an App to manage the agent with proper session handling
        from google.adk import App

        app = App(agent=self._adk_agent)

        print(f"\n> Host Agent Interactive Session")
        print(f"Session ID: {self.session_id}")
        print(f"Registered agents: {len(self.agent_manager.list_agents())}")
        print("Type 'q' or 'quit' to exit.\n")

        while True:
            user_input = input("You: ").strip()

            if user_input.lower() in ["q", "quit"]:
                print("Goodbye!")
                break

            if not user_input:
                continue

            try:
                # Process message through ADK app
                print("\nAssistant: ", end="", flush=True)

                # Use app.run_async which handles all the context setup
                response_text = []
                async for event in app.run_async(user_input):
                    # Extract text from event content
                    if hasattr(event, 'content') and event.content:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                text = part.text
                                print(text, end="", flush=True)
                                response_text.append(text)

                print("\n")  # New line after response

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                print(f"\nError: {e}\n")
