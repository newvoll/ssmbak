"""Tests that verify region handling works correctly."""

import os
import time
from datetime import datetime, timedelta, timezone

import boto3
import pytest

from ssmbak.restore.actions import ParamPath
from tests.helpers import rando

ALT_REGION = "eu-west-1"
ALT_BUCKET = "ssmbak-test-alt-region"
ALT_PATH = "/testmultiregion"


def simulate_backup(s3, ssm, bucket, name, value, param_type="String"):
    """Simulate what ssmbak.backup does: write to S3 with tags."""
    # Create SSM param
    ssm.put_parameter(Name=name, Value=value, Type=param_type, Overwrite=True)

    # Write to S3 with backup tags (what Lambda does)
    # NOTE: ssmbak.backup keeps the leading slash in the S3 key
    now = int(datetime.now(tz=timezone.utc).timestamp())
    s3.put_object(
        Bucket=bucket,
        Key=name,  # Keep leading slash to match ssmbak.backup behavior
        Body=value,
        Tagging=f"ssmbakTime={now}&ssmbakType={param_type}",
    )


@pytest.fixture
def alt_region_resources():
    """Set up resources in alternate region, clean up after."""
    endpoint = os.getenv("AWS_ENDPOINT")
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name=ALT_REGION)
    ssm = boto3.client("ssm", endpoint_url=endpoint, region_name=ALT_REGION)

    # Create bucket with versioning
    try:
        s3.create_bucket(
            Bucket=ALT_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": ALT_REGION},
        )
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    s3.put_bucket_versioning(
        Bucket=ALT_BUCKET,
        VersioningConfiguration={"Status": "Enabled"},
    )

    yield {"s3": s3, "ssm": ssm, "bucket": ALT_BUCKET, "region": ALT_REGION}

    # Cleanup: wipe SSM params in alt region
    paginator = ssm.get_paginator("get_parameters_by_path")
    for page in paginator.paginate(Path=ALT_PATH, Recursive=True):
        names = [p["Name"] for p in page.get("Parameters", [])]
        if names:
            ssm.delete_parameters(Names=names)

    # Cleanup: wipe S3 versions (key includes leading slash)
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=ALT_BUCKET, Prefix=ALT_PATH):
        for version in page.get("Versions", []) + page.get("DeleteMarkers", []):
            s3.delete_object(
                Bucket=ALT_BUCKET,
                Key=version["Key"],
                VersionId=version["VersionId"],
            )


def test_backup_restore_alt_region(alt_region_resources):
    """Full backup/restore cycle in alternate region."""
    res = alt_region_resources
    name = f"{ALT_PATH}/{rando()}"
    value = rando()

    # Simulate backup in alt region
    simulate_backup(res["s3"], res["ssm"], res["bucket"], name, value)

    # Delete from SSM (so restore has something to do)
    res["ssm"].delete_parameter(Name=name)

    # Wait for backup timestamp to be in the past (ssmbakTime comparison uses <)
    time.sleep(1)

    # Preview using ParamPath with alt region
    pp = ParamPath(name, datetime.now(tz=timezone.utc), res["region"], res["bucket"])
    previews = pp.preview()

    assert len(previews) == 1
    assert previews[0]["Name"] == name
    assert previews[0]["Value"] == value

    # Restore
    pp.restore()

    # Verify param restored in alt region
    restored = res["ssm"].get_parameter(Name=name, WithDecryption=True)
    assert restored["Parameter"]["Value"] == value


def test_region_isolation(alt_region_resources):
    """Data in alt region not visible from default region."""
    res = alt_region_resources
    name = f"{ALT_PATH}/{rando()}"
    value = rando()

    # Backup in alt region
    simulate_backup(res["s3"], res["ssm"], res["bucket"], name, value)

    # Wait for backup timestamp to be in the past (ssmbakTime comparison uses <)
    time.sleep(1)

    # ParamPath with alt region should find it
    pp_alt = ParamPath(
        name, datetime.now(tz=timezone.utc), res["region"], res["bucket"]
    )
    assert len(pp_alt.preview()) == 1

    # ParamPath with default region + default bucket should NOT find it
    pp_default = ParamPath(
        name, datetime.now(tz=timezone.utc), pytest.region, pytest.bucketname
    )
    assert len(pp_default.preview()) == 0
