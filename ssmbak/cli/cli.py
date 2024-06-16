"""A CLI interface to the ssmbak library. It's barely a CLI interface
and more of a wrapper to the ssmbak lib. Its main function is to
restore an ssm path, either key or path (recursive or not) to their
state at a point in time (checktime).
"""

import argparse
import logging
import os
import pprint
import sys
from datetime import datetime, timezone
from importlib.metadata import metadata, version
from textwrap import wrap

from botocore.exceptions import ClientError, NoRegionError
from prettytable import PrettyTable

from ssmbak.cli import helpers
from ssmbak.restore.actions import Path

logger = logging.getLogger(__name__)
pp = pprint.PrettyPrinter(indent=4)
parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    prog=os.path.basename(__file__),
)
parser.add_argument("command", help="one of preview or restore")
parser.add_argument(
    "path",
    help="ssm/s3 path/ or key",
)
parser.add_argument(
    "checktime",
    help="""point-in-time (UTC) to retrieve latest values, e.g. 2022-08-03T21:10:00""",
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
    "-R",
    "--recursive",
    action="store_true",
    default=False,
    help="recursive, only for actual path not key",
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    default=False,
    help="increase logging verbosity",
)
parser.add_argument(
    "--version",
    action="version",
    version=f"{metadata('ssmbak')['Name']} {version('ssmbak')}",
    help="print the version and quit",
)
args = parser.parse_args()
checktime = datetime.strptime(args.checktime, "%Y-%m-%dT%H:%M:%S").replace(
    tzinfo=timezone.utc
)


def main():
    """Checks for necessary confs, invokes ssmbak method Path.command,
    and tries to print out a nice table of results..
    """
    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    try:
        region = helpers.sort_region(args.region)
        bucketname = helpers.sort_bucket(args.bucket, region)
        result = _do_path(bucketname, region)
        _print_outs(result)
    except KeyboardInterrupt:
        logger.fatal("Interrupted")
        sys.exit(1)
    except ClientError as e:
        logger.fatal(
            "%s: %s", e.response["Error"]["Code"], e.response["Error"]["Message"]
        )
        if e.response["Error"]["Code"] == "ParameterNotFound":
            logger.fatal("Couldn't find SSM bucket param set by the stack.")
        sys.exit(1)
    except NoRegionError as e:
        logger.fatal(e)
        logger.fatal(
            "Specify a region 1) as an argument, "
            "2) using env var AWS_DEFAULT_REGION, or "
            "3) region= in ~/.aws/config."
        )
        sys.exit(1)


def _do_path(bucketname, region):
    path = Path(args.path, checktime, region, bucketname, recurse=args.recursive)
    return getattr(path, args.command)()


def _limit_string(val, limit=40):
    return "\n".join(wrap(str(val), limit))


def _print_outs(outs):
    try:
        keys = set().union(*outs)
        for out in outs:
            for key in keys - out.keys():
                out[key] = ""
        table = PrettyTable()
        headings = list(outs[0])
        table.field_names = headings
        table.align = "l"
        for out in outs:
            if out:
                table.add_row([_limit_string(out[x]) for x in headings])
        if len(table.rows) > 0:
            print(table)
    except (TypeError, AttributeError):  # pprint if table trouble
        pp.pprint(outs)
    except (KeyError, IndexError):  # for none
        pass
