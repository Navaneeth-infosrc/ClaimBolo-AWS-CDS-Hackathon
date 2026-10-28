"""Email channel via Amazon SES (boto3 client: sesv2)."""
import os

import boto3

_ses = boto3.client("sesv2", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def send_email(to: str, subject: str, html: str, sender: str, configuration_set: str = "") -> str:
    params = dict(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [to]},
        Content={"Simple": {
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
        }},
    )
    if configuration_set:
        params["ConfigurationSetName"] = configuration_set  # delivery / bounce events
    return _ses.send_email(**params)["MessageId"]
