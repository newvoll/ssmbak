"""Generic S3 point-in-time CLI built on :class:`ssmbak.restore.s3.S3Path`.

Three subcommands:

  s3bak preview <key> <checktime> -b <bucket> [-r <region>]
  s3bak body    <key> <checktime> -b <bucket> -o <outfile> [-r <region>]
  s3bak restore <key> <checktime> -b <bucket> [-r <region>]

``-b/--bucket`` is required: s3bak is generic and not tied to an ssmbak install.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from importlib.metadata import metadata, version

from botocore.exceptions import ClientError, NoRegionError
from prettytable import PrettyTable

from ssmbak.cli import helpers
from ssmbak.restore.s3 import S3Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=["preview", "body", "restore"],
        help="one of preview, body, or restore",
    )
    parser.add_argument("key", help="s3 object key")
    parser.add_argument(
        "checktime",
        help="point-in-time (UTC) to retrieve latest version, e.g. 2024-06-09T12:00:00",
    )
    parser.add_argument("-b", "--bucket", required=True, help="versioned s3 bucket to query")
    parser.add_argument(
        "-r", "--region", default="", help="aws region, default same as boto/awscli"
    )
    parser.add_argument(
        "-o",
        "--outfile",
        default="",
        help="destination file for `body` (use - for stdout); required for body",
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
    return parser


def main() -> None:
    """Dispatch to the chosen subcommand."""
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    if args.command == "body" and not args.outfile:
        print("body requires -o/--outfile", file=sys.stderr)
        sys.exit(2)
    try:
        checktime = datetime.strptime(args.checktime, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        region = helpers.sort_region(args.region)
        s3path = S3Path(args.key, checktime, region, args.bucket)
        if args.command == "preview":
            _cmd_preview(s3path)
        elif args.command == "body":
            _cmd_body(s3path, args.outfile)
        else:
            _cmd_restore(s3path)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
    except ClientError as e:
        print(
            f"Error: {e.response['Error']['Code']}: {e.response['Error']['Message']}",
            file=sys.stderr,
        )
        sys.exit(1)
    except NoRegionError as e:
        print(f"Error: {e}", file=sys.stderr)
        print(
            "Specify a region 1) as an argument, "
            "2) using env var AWS_DEFAULT_REGION, or "
            "3) region= in ~/.aws/config.",
            file=sys.stderr,
        )
        sys.exit(1)


def _cmd_preview(s3path: S3Path) -> None:
    version_ = s3path.preview()
    if version_ is None:
        print(
            f"No version of {s3path.key} found at or before "
            f"{s3path.checktime.strftime('%Y-%m-%dT%H:%M:%S')}",
            file=sys.stderr,
        )
        sys.exit(1)
    _print_version(version_)


def _cmd_body(s3path: S3Path, outfile: str) -> None:
    version_ = s3path.preview()
    if version_ is None:
        print(
            f"No version of {s3path.key} found at or before "
            f"{s3path.checktime.strftime('%Y-%m-%dT%H:%M:%S')}",
            file=sys.stderr,
        )
        sys.exit(1)
    if version_.get("Deleted"):
        print(
            f"{s3path.key} was deleted at {version_['LastModified']}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"Found version {version_['VersionId']} from {version_['LastModified']} "
        f"({version_['Size']} bytes)",
        file=sys.stderr,
    )
    if outfile == "-":
        s3path.download_to(sys.stdout.buffer)
    else:
        with open(outfile, "wb") as fh:
            s3path.download_to(fh)


def _cmd_restore(s3path: S3Path) -> None:
    version_ = s3path.restore()
    if version_ is None:
        print(
            f"No version of {s3path.key} found at or before "
            f"{s3path.checktime.strftime('%Y-%m-%dT%H:%M:%S')}",
            file=sys.stderr,
        )
        sys.exit(1)
    _print_version(version_)


def _print_version(version_) -> None:
    table = PrettyTable()
    fields = ["Key", "LastModified", "VersionId"]
    if version_.get("Deleted"):
        fields.append("Deleted")
    table.field_names = fields
    table.align = "l"
    row = [version_["Key"], version_["LastModified"], version_["VersionId"]]
    if version_.get("Deleted"):
        row.append("True")
    table.add_row(row)
    print(table)
