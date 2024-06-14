"""Creates a cloudformation stack with resources needed for
event-driven backup of SSM Param changes.
"""

import argparse
import logging
import pprint
import sys
from importlib.metadata import version
from pathlib import Path

from botocore.exceptions import ClientError, NoRegionError, ParamValidationError

from ssmbak.cli import helpers
from ssmbak.cli.cfn import Stack

logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)
parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument(
    "stackname",
    help="The name of the Cloudformation stack to be created",
)
parser.add_argument(
    "command",
    help="create | bucketname | lambdaname | region | status",
)
parser.add_argument(
    "-r",
    "--region",
    help="aws region, defaults to boto's default",
    default="",
)
# pylint: disable=duplicate-code
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    default=False,
    help="increase logging verbosity",
)
# pylint: enable=duplicate-code
args = parser.parse_args()


def main():
    """Top-level, just to execute stack commands and handle the exceptions."""
    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    try:
        region = helpers.sort_region(args.region)
        _do_cfn(region)
    # pylint: disable=duplicate-code
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(1)
    except ClientError as e:
        logger.fatal(
            "%s: %s", e.response["Error"]["Code"], e.response["Error"]["Message"]
        )
        sys.exit(1)
    except ParamValidationError:
        logger.fatal("ParamValidationError")
        sys.exit(1)
    except NoRegionError as e:
        logger.fatal(e)
        logger.fatal(
            "Specify a region 1) as an argument, "
            "2) using env var AWS_DEFAULT_REGION, or "
            "3) region= in ~/.aws/config."
        )
        sys.exit(1)
    # pylint: enable=duplicate-code


def _do_cfn(region):
    stack = Stack(args.stackname, region)
    if args.command in ["create", "update"]:
        template_dir = Path(__file__).parent.parent
        template_file = f"{template_dir}/data/cfn.yml"
        getattr(stack, args.command)(template_file, {"Version": version("ssmbak")})
        yay = stack.watch()
        if yay and args.command == "create":
            print()
            print(f"Lambda: {stack.lambdaname}")
            print(f"Bucket: {stack.bucketname}")
            print(f"Cloudwatch log group: /aws/lambda/{stack.lambdaname}")
            print()
            print(
                "ssmbak-all will back up all ssm params if provided --do-it, "
                "list if not"
            )
            print()
        elif args.command == "create":
            print(
                "Check the error messages above. Are you sure you have enough privs"
                "to create all those resources?"
            )
    elif args.command == "bucketname":
        print(stack.bucketname)
    elif args.command == "lambdaname":
        print(stack.lambdaname)
    elif args.command == "region":
        print(stack.region)
    elif args.command == "status":
        print(stack.status())
    else:
        print("Not a command.")
