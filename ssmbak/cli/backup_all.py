"""This script re-updates all SSM Params with optional prefix with the
same values. Tags are automatically maintained. Its purpose is to
initialize ssmbak backup store once its Lambda function is in
place. It will process all the events and back up each reupdated SSM
Param. Advanced params are not tested.
"""

import argparse
import logging
import os
import sys
from datetime import datetime

import boto3
from botocore.exceptions import ClientError, NoRegionError

from ssmbak.backup import ssmbak
from ssmbak.cli import helpers

logger = logging.getLogger(__name__)


# pylint: disable=duplicate-code
parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument(
    "-r",
    "--region",
    help="aws region, default same as boto/awscli",
    default="",
)
parser.add_argument(
    "-b",
    "--bucket",
    help="bucket that the lambda backs up to",
    default="",
)
parser.add_argument(
    "-p",
    "--prefix",
    help="""only perform reupdates under prefix/, still recursively.
    Can have multiple, e.g. -p /this /that""",
    nargs="+",
    default=[],
)
parser.add_argument(
    "--do-it",
    help="actually perform the reupdate",
    action="store_true",
    default=False,
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    default=False,
    help="increase logging verbosity",
)
args = parser.parse_args()
# pylint: enable=duplicate-code
ssm = boto3.client(
    "ssm",
    endpoint_url=os.getenv("AWS_ENDPOINT"),
    region_name=helpers.sort_region(args.region),
)


def _get_params(names):
    if names:
        response = ssm.get_parameters(Names=names, WithDecryption=True)
        params = response["Parameters"]
        keyed_params = {}
        for name in {x["Name"] for x in params}:
            key_params = [x for x in params if x["Name"] == name]
            keyed_params[name] = key_params[0]
    else:
        keyed_params = {}
    return keyed_params


def main():
    """Sorts region and bucket before backups."""
    # pylint: disable=duplicate-code
    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    try:
        region = helpers.sort_region(args.region)
        bucketname = helpers.sort_bucket(args.bucket, region)
        backup(bucketname)
    except KeyboardInterrupt:
        logger.fatal("Interrupted")
        sys.exit(1)
    except NoRegionError as e:
        logger.fatal(e)
        logger.fatal(
            "Specify a region 1) as an argument, "
            "2) using env var AWS_DEFAULT_REGION, or "
            "3) region= in ~/.aws/config."
        )
        sys.exit(1)
    except ClientError as e:
        logger.fatal(
            "%s: %s", e.response["Error"]["Code"], e.response["Error"]["Message"]
        )
        sys.exit(1)
    # pylint: enable=duplicate-code


def backup(bucketname):
    """Filters by path, and backs up ssm params using the same function as the lambda.

    Dry run default, --do-it to actually back up. Doesn't modify any SSM params.
    """
    paginator = ssm.get_paginator("describe_parameters")
    kwargs = {}
    if args.prefix:
        kwargs["ParameterFilters"] = [
            {
                "Key": "Name",
                "Option": "BeginsWith",
                "Values": args.prefix,
            }
        ]
    for page in paginator.paginate(**kwargs):
        params = page["Parameters"]
        for param in params:
            action = {
                "name": param["Name"],
                "type": param["Type"],
                "operation": "Update",
                "time": datetime.now(),
            }
            if "Description" in param:
                action["description"] = param["Description"]
            print(action)
            if args.do_it:
                os.environ["SSMBAK_BUCKET"] = bucketname  # ssmbak.py requires this
                ssmbak.backup(action)
    if not args.do_it:
        print()
        print("That's what would have been backed-up. --do-it to actually perform.")
    else:
        print()
        print("Above was backed-up.")
