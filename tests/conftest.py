"""Preps defaults and state for tests"""

import logging
import os
import sys
import time

import boto3
import pytest
from botocore.exceptions import ClientError

from ssmbak.restore.aws import Resource

logger = logging.getLogger(__name__)


def pytest_configure():
    """Effectively global vars, including some functions."""
    pytest.test_path = "/testyssmbak"
    try:
        pytest.region = os.environ["AWS_DEFAULT_REGION"]
        pytest.bucketname = os.environ["SSMBAK_BUCKET"]
    except KeyError:
        print(
            f"Env vars AWS_DEFAULT_REGION (={os.getenv('AWS_DEFAULT_REGION')})"
            f"and SSMBAK_BUCKET (={os.getenv('SSMBAK_BUCKET')}) must both be set!"
        )
        pytest.exit(1)
    pytest.s3 = boto3.client("s3", endpoint_url=os.getenv("AWS_ENDPOINT"))
    pytest.ssm = boto3.client("ssm", endpoint_url=os.getenv("AWS_ENDPOINT"))
    pytest.s3res = boto3.resource(
        "s3",
        endpoint_url=os.getenv("AWS_ENDPOINT"),
        region_name=pytest.region,
    )
    pytest.check_local = check_local
    pytest.ssmgetpath = ssmgetpath
    logging.getLogger("botocore").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.INFO)


def check_local():
    """Check for localstack, mainly to skip lambda tests if not."""
    return os.getenv("AWS_ENDPOINT") in [
        "http://localhost:4566",
        "http://localstack:4566",
    ]


def _wipe_s3_pages(paginated):
    for page in paginated:
        versions = []
        if "Versions" in page:
            versions.extend(page["Versions"])
        if "DeleteMarkers" in page:
            versions.extend(page["DeleteMarkers"])
        for version in versions:
            logger.debug("deleting %s %s", version["Key"], version["VersionId"])
            pytest.s3.delete_object(
                Bucket=pytest.bucketname,
                Key=version["Key"],
                VersionId=version["VersionId"],
            )


def wipe_s3():
    """Wipes s3 bucket pytest.test_path of all versions and verifies they're gone."""
    logger.debug("Wiping s3 bucket %s...", pytest.bucketname)
    paginator = pytest.s3.get_paginator("list_object_versions")
    paginated = paginator.paginate(Bucket=pytest.bucketname, Prefix=pytest.test_path)
    _wipe_s3_pages(paginated)
    empty = False
    now = time.time()
    timeout = 240
    while not empty:
        if time.time() > now + timeout:
            logger.critical("wipe timed out")
            sys.exit(1)
        paginator = pytest.s3.get_paginator("list_object_versions")
        paginated = paginator.paginate(
            Bucket=pytest.bucketname, Prefix=pytest.test_path
        )
        res = paginated.build_full_result()
        if "Versions" in res or "DeleteMarkers" in res:
            _wipe_s3_pages(paginated)
            logger.debug("sleeping")
            time.sleep(1)
        else:
            empty = True


def ssmdel(names):
    """Deletes each param in the given list."""
    batch_size = 10
    chunks = [names[x : x + batch_size] for x in range(0, len(names), batch_size)]
    for chunk in chunks:
        pytest.ssm.delete_parameters(Names=chunk)
        logger.debug("deleted %s", chunk)
    return names


def init_bucket():
    """Initializes bucket with versioning, which comes from environment."""
    logger.debug("bucketname: %s", pytest.bucketname)
    try:
        pytest.s3.create_bucket(
            Bucket=pytest.bucketname,
            CreateBucketConfiguration={"LocationConstraint": pytest.region},
        )
    except ClientError:
        # will fail if no bucket
        res = pytest.s3.get_bucket_acl(Bucket=pytest.bucketname)["ResponseMetadata"][
            "HTTPStatusCode"
        ]
        logger.debug("%s", res)
    pytest.s3.put_bucket_versioning(
        Bucket=pytest.bucketname,
        VersioningConfiguration={"Status": "Enabled"},
    )


def wipe_ssm():
    """Wipes all ssm vars from pytest.test_path."""
    logger.debug("Wiping SSM params...")
    names = [x["Name"] for x in ssmgetpath(pytest.test_path)]
    now = time.time()
    timeout = 120
    while names:
        dels = ssmdel(names)
        logger.debug("deleted %s from %s", dels, pytest.region)
        if time.time() > now + timeout:
            logger.critical("wipe timed out")
            sys.exit(1)
        time.sleep(1)
        names = [x["Name"] for x in ssmgetpath(pytest.test_path)]
        logger.debug("sleeping: %s", names)
        if not names:
            break
    assert not ssmgetpath(pytest.test_path)


def ssmgetpath(path):
    """Returns all ssm params in given path."""
    paginator = pytest.ssm.get_paginator("get_parameters_by_path")
    paginated = paginator.paginate(Path=path, Recursive=True, WithDecryption=True)
    try:
        res = paginated.build_full_result()["Parameters"]
    except ClientError as e:
        if e.response["Error"]["Code"] in ["ValidationException"]:
            time.sleep(1)
            res = paginated.build_full_result()["Parameters"]
        else:
            raise e
    return res


@pytest.fixture(autouse=True)
def init_tests():
    """Preps each test before running.

    Caches are cleared for call counts, only used in testing.
    """
    Resource(pytest.region, pytest.bucketname).clear_call_cache()
    init_bucket()
    wipe_ssm()
    wipe_s3()
    yield True
