import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_kms as kms,
    aws_s3 as s3,
    aws_ses as ses,
    aws_sns as sns,
)
from constructs import Construct

from stacks.ingest import Ingest


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"Set the {name} environment variable before deploying (see .env.example)")
    return value


class FoundationStack(Stack):
    """Shared storage, messaging topic and data tables. Everything is destroyable with `cdk destroy`."""

    def __init__(self, scope: Construct, construct_id: str, *, prefix: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        key = kms.Key(
            self,
            "DataKey",
            alias=f"alias/{prefix}",
            description="ClaimBolo data encryption key",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Inbound and outbound WhatsApp media (voice notes, photos)
        media_bucket = s3.Bucket(
            self,
            "MediaBucket",
            bucket_name=f"{prefix}-media-{self.account}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # End User Messaging Social publishes inbound messages and delivery events here
        inbound_topic = sns.Topic(
            self,
            "WhatsappInboundTopic",
            topic_name=f"{prefix}-whatsapp-inbound",
            display_name="ClaimBolo WhatsApp events",
        )
        inbound_topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowEndUserMessagingSocialPublish",
                principals=[iam.ServicePrincipal("social-messaging.amazonaws.com")],
                actions=["sns:Publish"],
                resources=[inbound_topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )

        def table(logical_id: str, name: str, pk: str, sk: str | None = None) -> ddb.Table:
            return ddb.Table(
                self,
                logical_id,
                table_name=f"{prefix}-{name}",
                partition_key=ddb.Attribute(name=pk, type=ddb.AttributeType.STRING),
                sort_key=ddb.Attribute(name=sk, type=ddb.AttributeType.STRING) if sk else None,
                billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
                encryption_key=key,
                removal_policy=RemovalPolicy.DESTROY,
            )

        policies = table("PoliciesTable", "policies", "phone")
        claims = table("ClaimsTable", "claims", "claim_id")
        claims.add_global_secondary_index(
            index_name="phone-index",
            partition_key=ddb.Attribute(name="phone", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="created_at", type=ddb.AttributeType.STRING),
        )
        conversations = table("ConversationsTable", "conversations", "phone", "ts")
        audit = table("AuditTable", "audit", "claim_id", "ts")

        # De-duplicates repeated WhatsApp/SNS deliveries; rows expire on their own
        processed = table("ProcessedMessagesTable", "processed-messages", "message_id")
        processed.node.default_child.add_property_override(
            "TimeToLiveSpecification", {"AttributeName": "expires_at", "Enabled": True}
        )

        # Delivery, bounce and complaint events for sent email
        email_events = ses.CfnConfigurationSet(self, "EmailEvents", name=f"{prefix}-events")

        Ingest(
            self,
            "Ingest",
            prefix=prefix,
            key=key,
            media_bucket=media_bucket,
            inbound_topic=inbound_topic,
            tables={"POLICIES_TABLE": policies, "CLAIMS_TABLE": claims, "CONVERSATIONS_TABLE": conversations,
                    "AUDIT_TABLE": audit, "PROCESSED_TABLE": processed},
            whatsapp_phone_number_id=_required("WHATSAPP_PHONE_NUMBER_ID"),
            model_id=_required("MODEL_ID"),
            ses_sender=os.environ.get("SES_SENDER", ""),
            adjuster_email=os.environ.get("ADJUSTER_EMAIL", ""),
            email_config_set=email_events.name,
            demo_mode=os.environ.get("DEMO_MODE", "true"),
        )

        for logical_id, value in {
            "MediaBucketName": media_bucket.bucket_name,
            "WhatsappInboundTopicArn": inbound_topic.topic_arn,
            "DataKeyArn": key.key_arn,
            "PoliciesTableName": policies.table_name,
            "ClaimsTableName": claims.table_name,
            "ConversationsTableName": conversations.table_name,
            "AuditTableName": audit.table_name,
            "ProcessedMessagesTableName": processed.table_name,
            "EmailConfigurationSet": email_events.name,
        }.items():
            CfnOutput(self, logical_id, value=value)
