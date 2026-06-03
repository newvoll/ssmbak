"""Integration tests for S3Path against LocalStack.

Exercises real put/delete/list_object_versions calls on a versioned bucket;
no SSM involvement.
"""

import io
import logging
import time
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError

from ssmbak.restore.s3 import S3Path
from tests import helpers

logger = logging.getLogger(__name__)


def _key():
    return f"{pytest.test_path}/{helpers.rando()}"


def _put(key, body):
    """Put an object and return the response (which includes VersionId)."""
    return pytest.s3.put_object(Bucket=pytest.bucketname, Key=key, Body=body.encode())


def _delete(key):
    """Issue a delete (creates a delete marker on the versioned bucket)."""
    return pytest.s3.delete_object(Bucket=pytest.bucketname, Key=key)


def _now():
    return datetime.now(tz=UTC)


def test_preview_real_version():
    """preview at a time between two puts returns the earlier version."""
    key = _key()
    _put(key, "first")
    r1 = pytest.s3.head_object(Bucket=pytest.bucketname, Key=key)
    vid1 = r1["VersionId"]
    # Ensure second-level separation since use_tags=False compares at sec precision
    time.sleep(1)
    between = _now()
    time.sleep(1)
    _put(key, "second")
    preview = S3Path(key, between, pytest.region, pytest.bucketname).preview()
    assert preview is not None
    assert preview["VersionId"] == vid1
    assert preview["Key"] == key
    assert preview.get("Deleted") is None or preview.get("Deleted") is False


def test_preview_delete_marker():
    """After a delete, preview at a later time returns Deleted: True."""
    key = _key()
    _put(key, "alive")
    time.sleep(1)
    _delete(key)
    time.sleep(1)
    after = _now()
    preview = S3Path(key, after, pytest.region, pytest.bucketname).preview()
    assert preview is not None
    assert preview.get("Deleted") is True


def test_preview_missing_returns_none():
    """preview at a time before any version returns None."""
    key = _key()
    before = _now() - timedelta(days=1)
    _put(key, "after")
    preview = S3Path(key, before, pytest.region, pytest.bucketname).preview()
    assert preview is None


def test_body_real_version():
    """body() returns the put content."""
    key = _key()
    _put(key, "hello body")
    time.sleep(1)
    later = _now()
    s3p = S3Path(key, later, pytest.region, pytest.bucketname)
    assert s3p.body() == "hello body"


def test_body_delete_marker_returns_empty():
    """body() returns empty string when current version at checktime is a delete marker."""
    key = _key()
    _put(key, "alive")
    time.sleep(1)
    _delete(key)
    time.sleep(1)
    after = _now()
    s3p = S3Path(key, after, pytest.region, pytest.bucketname)
    assert s3p.body() == ""


def test_body_missing_returns_empty():
    """body() returns empty string when no version exists at checktime."""
    key = _key()
    before = _now() - timedelta(days=1)
    _put(key, "post")
    s3p = S3Path(key, before, pytest.region, pytest.bucketname)
    assert s3p.body() == ""


def test_download_to_real_version():
    """download_to streams bytes that match what was put."""
    key = _key()
    _put(key, "stream me")
    time.sleep(1)
    later = _now()
    s3p = S3Path(key, later, pytest.region, pytest.bucketname)
    buf = io.BytesIO()
    s3p.download_to(buf)
    assert buf.getvalue() == b"stream me"


def test_download_to_delete_marker_raises():
    """download_to raises ValueError when relevant version is a delete marker."""
    key = _key()
    _put(key, "alive")
    time.sleep(1)
    _delete(key)
    time.sleep(1)
    after = _now()
    s3p = S3Path(key, after, pytest.region, pytest.bucketname)
    with pytest.raises(ValueError):
        s3p.download_to(io.BytesIO())


def test_download_to_missing_raises():
    """download_to raises ValueError when there's no version at checktime."""
    key = _key()
    before = _now() - timedelta(days=1)
    _put(key, "post")
    s3p = S3Path(key, before, pytest.region, pytest.bucketname)
    with pytest.raises(ValueError):
        s3p.download_to(io.BytesIO())


def test_restore_real_version():
    """restore copies an old version; current content matches the restored one."""
    key = _key()
    _put(key, "v1")
    time.sleep(1)
    between = _now()
    time.sleep(1)
    _put(key, "v2")
    # current should be v2
    assert (
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=key)["Body"].read()
        == b"v2"
    )
    s3p = S3Path(key, between, pytest.region, pytest.bucketname)
    result = s3p.restore()
    assert result is not None
    # current should now be v1's content again
    assert (
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=key)["Body"].read()
        == b"v1"
    )


def test_restore_delete_marker():
    """restore of a delete-marker state removes the current object."""
    key = _key()
    _put(key, "alive")
    time.sleep(1)
    _delete(key)
    time.sleep(1)
    after = _now()
    time.sleep(1)
    _put(key, "resurrected")
    # current exists again
    assert (
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=key)["Body"].read()
        == b"resurrected"
    )
    s3p = S3Path(key, after, pytest.region, pytest.bucketname)
    result = s3p.restore()
    assert result is not None
    assert result.get("Deleted") is True
    # current should be deleted again
    with pytest.raises(ClientError) as exc:
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=key)
    assert exc.value.response["Error"]["Code"] in {"NoSuchKey", "404"}


def test_restore_missing_returns_none():
    """restore returns None when nothing exists at checktime; bucket untouched."""
    key = _key()
    before = _now() - timedelta(days=1)
    _put(key, "live")
    s3p = S3Path(key, before, pytest.region, pytest.bucketname)
    assert s3p.restore() is None
    # current still there
    assert (
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=key)["Body"].read()
        == b"live"
    )
