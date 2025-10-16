import uuid
import boto3
import json

from utils import get_aws_info, get_ssm_parameter

account_id, region = get_aws_info()

# Initialize the Bedrock AgentCore client
agent_core_client = boto3.client("bedrock-agentcore")

host_agent_id = get_ssm_parameter("/hostagent/agentcore/runtime-id")
host_agent_arn = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{host_agent_id}"
)


if __name__ == "__main__":
    # Start interactive session
    session_id = str(uuid.uuid4())
    print(f"\n🤖 Starting interactive session (Session ID: {session_id})")
    print("Type 'q' or 'quit' to exit.\n")

    while True:
        user_input = input("👤 You: ").strip()

        if user_input.lower() in ["q", "quit"]:
            print("👋 Goodbye!")
            break

        if not user_input:
            continue

        payload = json.dumps({"prompt": user_input}).encode()

        response = agent_core_client.invoke_agent_runtime(
            agentRuntimeArn=host_agent_arn, runtimeSessionId=session_id, payload=payload
        )

        # Process and print the response
        if "text/event-stream" in response.get("contentType", ""):
            # Handle streaming response
            content = []
            for line in response["response"].iter_lines(chunk_size=10):
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        line = line[6:]
                        print(line)
                        content.append(line)
            print("\nComplete response:", "\n".join(content))

        elif response.get("contentType") == "application/json":
            # Handle standard JSON response
            content = []
            for chunk in response.get("response", []):
                content.append(chunk.decode("utf-8"))
            print(json.loads("".join(content)))

        else:
            # Print raw response for other content types
            print(response)
        print()
