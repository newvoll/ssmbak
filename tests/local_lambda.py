"""Alternative to ssmbak.backup for more thorough integration testing."""

import logging

import requests

logger = logging.getLogger(__name__)


def backup(action):
    """Will hit localstack's lambda instead of using the lib."""
    r = requests.post(
        "http://localhost:9000/2015-03-31/functions/function/invocations",
        json=action,
        timeout=10,
    )
    logger.debug("status_code: %s", r.status_code)
    # this means little
    assert r.status_code == 200
    return r


def process_message(body: str) -> dict:
    """Message is encapsulated when coming in from EventBridge via SQS."""
    message = {
        "Records": [
            {
                "messageId": "07e34a99-5480-4c7c-bc0b-44ea9c74076b",
                "receiptHandle": "XXX=",
                "body": body,
                "attributes": {
                    "ApproximateReceiveCount": "1",
                    "SentTimestamp": "1660007032420",
                    "SenderId": "AIDAJXNJGGKNS7OSV23OI",
                    "ApproximateFirstReceiveTimestamp": "1660007032431",
                },
                "messageAttributes": {},
                "md5OfBody": "08a526cb73b963e532b0380646063f3b",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:someQ",
                "awsRegion": "us-east-1",
            }
        ]
    }
    return message
