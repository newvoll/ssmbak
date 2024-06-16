"""AWS Lambda function used to backup SSM param change events."""

import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from typing import Union

import boto3
from botocore.exceptions import ClientError

LEVEL = os.getenv("LOGLEVEL", "INFO")
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LEVEL))


def process_message(body: str) -> dict[str, Union[str, datetime]]:
    """Transforms a message from EventBridge (via SQS) to friendly format.

    NOTE: for some reason only top-level key names arrive without a
    prepending slash. In that case, we prepend at the note PREPEND.

    Arguments:
      body: json-formatted string from the event

    Returns:

      A dict with the info needed for backup, including time of event.
      {
          "name": "/testyssmbak/023179",
          "type": "SecureString",
          "operation": "Create",
          "time": datetime.datetime(2022, 8, 3, 21, 9, 31, tzinfo=datetime.timezone.utc),
          "description": "fancy description", --OPTIONAL
      }
    """
    logger.debug("body: %s", body)
    message = json.loads(body)
    logger.debug("message: %s", message)
    checktime = datetime.strptime(message["time"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    action = {
        "name": message["detail"]["name"],
        "type": message["detail"]["type"],
        "operation": message["detail"]["operation"],
        "time": checktime,
    }
    if "description" in message["detail"]:
        action["description"] = message["detail"]["description"]
    if not action["name"].startswith("/"):  # PREPEND
        logger.debug("prepending %s with a /", action["name"])
        action["name"] = f"/{action['name']}"
    return action


def backup(action: dict) -> int:
    """Backs up the processed SSM event to S3, tagging with details.

    If an SSM param was deleted before it could get processed, it is
    logged and skipped. Tagging is used for metadata like description
    and time of event.

    Arguments:
      action: dict as returned by process_message.

    Returns:
      HTTP status code of call to S3 api.

    """
    try:
        bucketname = os.environ["SSMBAK_BUCKET"]
    except KeyError:
        logger.critical("SSMBAK_BUCKET env var must be set! Dying...")
        sys.exit(1)
    logger.debug("action: %s", action)
    s3 = boto3.client("s3", endpoint_url=os.getenv("AWS_ENDPOINT"))
    ssm = boto3.client("ssm", endpoint_url=os.getenv("AWS_ENDPOINT"))
    kwargs = {"Bucket": bucketname, "Key": action["name"]}
    if action["operation"] == "Delete":
        method = "delete_object"
    else:
        method = "put_object"
        ssm_kwargs = {"Name": action["name"], "WithDecryption": True}
        try:
            response = ssm.get_parameter(**ssm_kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ParameterNotFound":
                logger.warning("Skipping %s. Deleted before backup.", action["name"])
                return 204
        value = response["Parameter"]["Value"]
        tags = {
            "ssmbakTime": int(action["time"].timestamp()),
            "ssmbakType": action["type"],
        }
        if "description" in action:
            tags["ssmbakDescription"] = action["description"]
        kwargs["Tagging"] = urllib.parse.urlencode(tags)
        logger.debug("kwargs[Tagging]: %s", kwargs["Tagging"])
        kwargs["Body"] = value
    logger.info("%s %s", method, str(kwargs))
    result = getattr(s3, method)(**kwargs)
    return result["ResponseMetadata"]["HTTPStatusCode"]


def process_event(event: dict[str, list[dict[str, Union[str, dict]]]]) -> int:
    """Extracts the body from the event for backup

    Arguments:
      event: dict of event coming in from EventBridge via SQS
        {
            "Records": [
                {
                    "messageId": "07e34a99-5480-4c7c-bc0b-44ea9c74076b",
                    "receiptHandle": "XXX=",
                    "body": '{"version": "0", "id": "2ada935b-482a-1f19-50a1-21aa9b6b7e2c", "detail-type": "Parameter Store Change", "source": "aws.ssm", "account": "000000000000", "time": "2024-06-08T23:06:33Z", "region": "us-east-1", "resources": ["arn:aws:ssm:us-east-1:000000000000:parameter/testssmbak/bas/desctest"], "detail": {"name": "/testyssmbak/H0PTBA", "description": "fancydesc2", "type": "SecureString", "operation": "Update"}}',
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

    Returns:
      Boolean which is kind of useless.
    """  # pylint: disable=line-too-long
    for record in event["Records"]:
        param_action = process_message(record["body"])
        if param_action["operation"] in ["Create", "Update", "Delete"]:
            res = backup(param_action)
        else:
            logger.warning(
                "skipping %s %s", param_action["operation"], param_action["name"]
            )
            res = 205
        logger.info("result: %s", res)
    return res


def handler(event: dict, context) -> int:  # pylint: disable=unused-argument
    """Skipping module import just for context typing."""
    return process_event(event)
