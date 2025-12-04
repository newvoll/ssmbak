#!/usr/bin/env python3
"""Build CloudFormation template with embedded Lambda code.

Reads the cfn.yml template and ssmbak.py Lambda code, injects the code
into the template's ZipFile field, and outputs a versioned template file.

Usage:
    python scripts/build_template.py              # build only
    python scripts/build_template.py --upload     # build and upload to S3
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

# Repo root for finding files
REPO_ROOT = Path(__file__).parent.parent
BUCKET_NAME = "ssmbak-public"
BUCKET_REGION = "us-east-2"


def get_version() -> str:
    """Get version from pyproject.toml."""
    pyproject = REPO_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


# CloudFormation intrinsic function support for YAML load/dump


def _cfn_constructor(loader, tag_suffix, node):
    """Handle CloudFormation intrinsic functions like !Ref, !GetAtt, !Sub."""
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node)}
    if isinstance(node, yaml.MappingNode):
        return {tag_suffix: loader.construct_mapping(node)}
    return {tag_suffix: node.value}


yaml.SafeLoader.add_multi_constructor("!", _cfn_constructor)


def _cfn_representer(dumper, data):
    """Represent CloudFormation intrinsic functions with ! tag syntax."""
    if isinstance(data, dict) and len(data) == 1:
        key = next(iter(data))
        cfn_functions = {
            "Ref",
            "Condition",
            "GetAtt",
            "Sub",
            "Join",
            "Select",
            "Split",
            "FindInMap",
            "GetAZs",
            "ImportValue",
            "Base64",
            "Cidr",
            "If",
            "And",
            "Or",
            "Not",
            "Equals",
        }
        if key in cfn_functions:
            value = data[key]
            if isinstance(value, str):
                return dumper.represent_scalar(f"!{key}", value)
            if isinstance(value, list):
                return dumper.represent_sequence(f"!{key}", value)
            if isinstance(value, dict):
                return dumper.represent_mapping(f"!{key}", value)
    return dumper.represent_dict(data)


class CfnDumper(yaml.SafeDumper):
    """YAML dumper with CloudFormation intrinsic function support."""


CfnDumper.add_representer(dict, _cfn_representer)


def build_template(template_path: Path, lambda_path: Path) -> str:
    """Build template with embedded Lambda code."""
    with open(template_path, encoding="utf-8") as f:
        template = yaml.safe_load(f)

    lambda_code = lambda_path.read_text(encoding="utf-8")
    template["Resources"]["Function"]["Properties"]["Code"]["ZipFile"] = lambda_code

    return yaml.dump(template, Dumper=CfnDumper, default_flow_style=False)


def upload_to_s3(local_path: Path, s3_key: str, profile: str | None = None) -> str:
    """Upload file to S3 bucket."""
    import boto3

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3", region_name=BUCKET_REGION)
    s3.upload_file(
        str(local_path),
        BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": "application/x-yaml"},
    )
    return f"https://{BUCKET_NAME}.s3.{BUCKET_REGION}.amazonaws.com/{s3_key}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upload",
        action="store_true",
        help=f"Upload to s3://{BUCKET_NAME}/",
    )
    parser.add_argument(
        "--profile",
        "-p",
        help="AWS profile to use for upload",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path (default: dist/cfn-{version}.yml)",
    )
    args = parser.parse_args()

    template_path = REPO_ROOT / "ssmbak" / "data" / "cfn.yml"
    lambda_path = REPO_ROOT / "ssmbak" / "backup" / "ssmbak.py"

    try:
        ver = get_version()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        dist_dir = REPO_ROOT / "dist"
        dist_dir.mkdir(exist_ok=True)
        output_path = dist_dir / f"cfn-{ver}.yml"

    # Build and write
    template_body = build_template(template_path, lambda_path)
    output_path.write_text(template_body, encoding="utf-8")
    print(f"Built {output_path} ({len(template_body)} bytes)")

    # Upload if requested
    if args.upload:
        s3_key = f"cfn-{ver}.yml"
        url = upload_to_s3(output_path, s3_key, args.profile)
        print(f"Uploaded to {url}")


if __name__ == "__main__":
    main()
