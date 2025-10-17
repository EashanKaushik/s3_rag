# Agent-2-Agent (A2A) Multi-Agent System on Amazon Bedrock AgentCore for Incident Response Logging

## Architecture Overview

```bash
TODO: Architecture video
```

## Demo

```bash
TODO: Demo video
```

## Prerequisites

1. **AWS Account**: You need an active AWS account with appropriate permissions
   - [Create AWS Account](https://aws.amazon.com/account/)
   - [AWS Console Access](https://aws.amazon.com/console/)

2. **AWS CLI**: Install and configure AWS CLI with your credentials
   - [Install AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
   - [Configure AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html)

   ```bash
   aws configure
   ```

3. **Bedrock Model Access**: Enable access to Amazon Bedrock Anthropic Claude 4.0 models in your AWS region
   - Navigate to [Amazon Bedrock Console](https://console.aws.amazon.com/bedrock/)
   - Go to "Model access" and request access to:
     - Anthropic Claude 4.0 Sonnet model
     - Anthropic Claude 3.5 Haiku model
   - [Amazon Bedrock Model Access Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)

4. Install uv using [guide](https://docs.astral.sh/uv/getting-started/installation/).

5. **Supported Regions**: This solution is currently tested and supported in the following AWS regions:

   | Region Code   | Region Name          | Status      |
   |---------------|----------------------|-------------|
   | `us-west-2`   | US West (Oregon)     | ✅ Supported |

   > **Note**: To deploy in other regions, you'll need to update the DynamoDB prefix list mappings in `cloudformation/vpc-stack.yaml`. See the [VPC Stack documentation](cloudformation/vpc-stack.yaml) for details.

## Deployment Steps

### Step 1: Deploy AWS Cognito Stack

```bash
aws cloudformation create-stack \
    --stack-name cognito-stack-a2a \
    --template-body file://cloudformation/cognito.yaml \
    --capabilities CAPABILITY_IAM \
    --region us-west-2
```

### Step 2: Deploy Monitoring Strands Agent

```bash
aws cloudformation create-stack \
    --stack-name monitor-agent-a2a \
    --template-body file://cloudformation/monitoring_agent.yaml \
    --capabilities CAPABILITY_IAM \
    --region us-west-2
```

