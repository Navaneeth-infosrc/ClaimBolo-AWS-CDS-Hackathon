from pathlib import Path

import build_runtime

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_bedrockagentcore as agentcore,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_kms as kms,
    aws_lambda as _lambda,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_assets as s3_assets,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
)
from constructs import Construct

SRC_DIR = Path(__file__).resolve().parents[2] / "src"


class Ingest(Construct):
    """WhatsApp in -> agent -> WhatsApp/email out, plus the adjuster view and proactive updates."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        key: kms.IKey,
        media_bucket: s3.IBucket,
        inbound_topic: sns.ITopic,
        tables: dict,
        whatsapp_phone_number_id: str,
        model_id: str,
        ses_sender: str,
        adjuster_email: str,
        email_config_set: str,
        demo_mode: str = "true",
    ) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)

        # Blocks prompt attacks in customer text and legal/medical or payout-promise replies
        guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name=f"{prefix}-guardrail",
            description="Keeps the claims agent on topic and away from payout promises",
            blocked_input_messaging="I can only help with your motor insurance claim.",
            blocked_outputs_messaging="I can only help with your motor insurance claim.",
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(filters_config=[
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE")]),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(topics_config=[
                bedrock.CfnGuardrail.TopicConfigProperty(
                    name="LegalOrMedicalAdvice", type="DENY",
                    definition="Giving legal advice or medical advice or diagnosing injuries.",
                    examples=["Should I sue the other driver?", "Is my neck pain serious, what medicine should I take?"]),
                bedrock.CfnGuardrail.TopicConfigProperty(
                    name="PayoutPromises", type="DENY",
                    definition="Promising, guaranteeing or estimating the amount of money an insurer will pay for a claim, or stating that a claim is approved or rejected.",
                    examples=["Your claim is approved and you will receive 40,000 rupees.",
                              "We will definitely pay the full repair cost."])]),
        )

        # AgentCore Memory: durable customer facts and session summaries, extracted from the conversation events
        memory = agentcore.CfnMemory(
            self,
            "Memory",
            name=f"{prefix.replace('-', '_')}_memory",
            description="ClaimBolo customer memory: language, preferences and conversation summaries",
            event_expiry_duration=90,
            memory_strategies=[
                agentcore.CfnMemory.MemoryStrategyProperty(
                    user_preference_memory_strategy=agentcore.CfnMemory.UserPreferenceMemoryStrategyProperty(
                        name="CustomerPreferences", namespaces=["/users/{actorId}/preferences"])),
                agentcore.CfnMemory.MemoryStrategyProperty(
                    summary_memory_strategy=agentcore.CfnMemory.SummaryMemoryStrategyProperty(
                        name="SessionSummaries", namespaces=["/summaries/{actorId}/{sessionId}"])),
            ],
        )

        adjuster_secret = secretsmanager.Secret(
            self,
            "AdjusterKey",
            secret_name=f"{prefix}-adjuster-key",
            generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=24),
            removal_policy=RemovalPolicy.DESTROY,
        )

        env = {
            **{name: t.table_name for name, t in tables.items()},
            "MEDIA_BUCKET": media_bucket.bucket_name,
            "WHATSAPP_PHONE_NUMBER_ID": whatsapp_phone_number_id,
            "MODEL_ID": model_id,
            "GUARDRAIL_ID": guardrail.attr_guardrail_id,
            "GUARDRAIL_VERSION": "DRAFT",
            "SES_SENDER": ses_sender,
            "ADJUSTER_EMAIL": adjuster_email,
            "SES_CONFIG_SET": email_config_set,
            "PROJECT_TAG": prefix,
            "MEMORY_ID": memory.attr_memory_id,
            "DEMO_MODE": demo_mode,
        }

        # The agent itself runs on Amazon Bedrock AgentCore Runtime (deployed from a code package, no container)
        package = s3_assets.Asset(self, "RuntimePackage", path=str(build_runtime.build()))
        runtime_role = iam.Role(
            self, "RuntimeRole", role_name=f"{prefix[:40]}-runtime-role",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"))
        for table in tables.values():
            table.grant_read_write_data(runtime_role)
        media_bucket.grant_read_write(runtime_role)
        key.grant_encrypt_decrypt(runtime_role)
        package.grant_read(runtime_role)
        runtime_role.add_to_policy(iam.PolicyStatement(actions=["ses:SendEmail"], resources=["*"]))
        runtime_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["arn:aws:bedrock:*::foundation-model/*",
                       f"arn:aws:bedrock:{stack.region}:{stack.account}:inference-profile/*"]))
        runtime_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn]))
        runtime_role.add_to_policy(iam.PolicyStatement(
            actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams",
                     "xray:PutTraceSegments", "xray:PutTelemetryRecords"], resources=["*"]))
        agent_runtime = agentcore.CfnRuntime(
            self, "AgentRuntime", agent_runtime_name=f"{prefix.replace('-', '_')}_agent",
            description="ClaimBolo claims agent: Guardrails, Bedrock tool-use loop and claim tools",
            role_arn=runtime_role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(s3=agentcore.CfnRuntime.S3LocationProperty(
                        bucket=package.s3_bucket_name, prefix=package.s3_object_key)),
                    runtime="PYTHON_3_12", entry_point=["main.py"])),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(network_mode="PUBLIC"),
            protocol_configuration="HTTP",
            environment_variables={**env, "AWS_REGION": stack.region, "AWS_DEFAULT_REGION": stack.region})
        agent_runtime.node.add_dependency(runtime_role)

        def function(logical_id: str, name: str, handler: str, timeout: int, memory: int = 256, extra=None,
                     logs_id: str | None = None):
            log_group = logs.LogGroup(
                self, logs_id or f"{logical_id}Logs", log_group_name=f"/aws/lambda/{prefix}-{name}",
                retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY)
            fn = _lambda.Function(
                self, logical_id, function_name=f"{prefix}-{name}", runtime=_lambda.Runtime.PYTHON_3_12,
                handler=handler, code=_lambda.Code.from_asset(str(SRC_DIR), exclude=["**/__pycache__", "**/*.pyc"]),
                timeout=Duration.seconds(timeout), memory_size=memory, log_group=log_group,
                environment={**env, **(extra or {})})
            for table in tables.values():
                table.grant_read_write_data(fn)
            media_bucket.grant_read_write(fn)
            key.grant_encrypt_decrypt(fn)
            return fn

        agent_fn = function("AgentHandler", "agent", "handlers.agent_handler.handler", 150, 512,
                            extra={"AGENT_RUNTIME_ARN": agent_runtime.attr_agent_runtime_arn})
        agent_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:InvokeAgentRuntime"],
            resources=[agent_runtime.attr_agent_runtime_arn, f"{agent_runtime.attr_agent_runtime_arn}/*"]))
        inbound_fn = function("InboundHandler", "inbound", "handlers.inbound.handler", 60,
                              extra={"AGENT_FUNCTION": agent_fn.function_name}, logs_id="InboundLogs")
        transcribe_fn = function("TranscribeComplete", "transcribe-complete", "handlers.transcribe_complete.handler", 60,
                                 extra={"AGENT_FUNCTION": agent_fn.function_name})
        proactive_fn = function("ProactiveNotifier", "proactive", "handlers.proactive.handler", 60)
        adjuster_fn = function("AdjusterView", "adjuster", "handlers.adjuster.handler", 30,
                               extra={"ADJUSTER_SECRET_ARN": adjuster_secret.secret_arn})

        agent_fn.grant_invoke(inbound_fn)
        agent_fn.grant_invoke(transcribe_fn)
        adjuster_secret.grant_read(adjuster_fn)

        phone_arn = f"arn:aws:social-messaging:{stack.region}:{stack.account}:phone-number-id/*"
        whatsapp_actions = ["social-messaging:GetWhatsAppMessageMedia", "social-messaging:SendWhatsAppMessage"]
        for fn in (inbound_fn, agent_fn, transcribe_fn, proactive_fn):
            fn.add_to_role_policy(iam.PolicyStatement(actions=whatsapp_actions, resources=[phone_arn]))
        for fn in (agent_fn, proactive_fn, inbound_fn):
            fn.add_to_role_policy(iam.PolicyStatement(actions=["ses:SendEmail"], resources=["*"]))
        agent_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=["arn:aws:bedrock:*::foundation-model/*",
                       f"arn:aws:bedrock:{stack.region}:{stack.account}:inference-profile/*"]))
        agent_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn]))
        agent_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents", "bedrock-agentcore:ListSessions",
                     "bedrock-agentcore:RetrieveMemoryRecords"],
            resources=[memory.attr_memory_arn]))
        for fn in (inbound_fn, transcribe_fn):
            fn.add_to_role_policy(iam.PolicyStatement(
                actions=["transcribe:StartTranscriptionJob", "transcribe:GetTranscriptionJob", "transcribe:TagResource"],
                resources=["*"]))
        adjuster_fn.add_to_role_policy(iam.PolicyStatement(actions=["events:PutEvents"], resources=["*"]))

        inbound_topic.add_subscription(subs.LambdaSubscription(inbound_fn))

        events.Rule(
            self, "TranscribeDone", rule_name=f"{prefix}-transcribe-done",
            event_pattern=events.EventPattern(
                source=["aws.transcribe"], detail_type=["Transcribe Job State Change"],
                detail={"TranscriptionJobStatus": ["COMPLETED", "FAILED"],
                        "TranscriptionJobName": [{"prefix": "claimbolo-"}]}),
            targets=[targets.LambdaFunction(transcribe_fn)])
        events.Rule(
            self, "ClaimStatusChanged", rule_name=f"{prefix}-claim-status-changed",
            event_pattern=events.EventPattern(source=["claimbolo"], detail_type=["ClaimStatusChanged"]),
            targets=[targets.LambdaFunction(proactive_fn)])

        url = adjuster_fn.add_function_url(auth_type=_lambda.FunctionUrlAuthType.NONE)
        CfnOutput(self, "AdjusterUrl", value=url.url)
        CfnOutput(self, "AdjusterSecretName", value=adjuster_secret.secret_name)
        CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id)
        CfnOutput(self, "AgentCoreMemoryId", value=memory.attr_memory_id)
        CfnOutput(self, "AgentCoreRuntimeArn", value=agent_runtime.attr_agent_runtime_arn)
