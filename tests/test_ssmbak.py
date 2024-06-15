"""Test suite for the lambda function, both lib and actual lambda (localstack)."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from ssmbak.backup import ssmbak

# pytype bug https://google.github.io/pytype/errors.html#pyi-error
from tests import helpers, local_lambda

logger = logging.getLogger(__name__)
name = f"{pytest.test_path}/{helpers.rando()}"


def slurp_helper(filename):
    """Slurps up content of helper file with filename."""
    return helpers.slurp(f"{Path(__file__).parent}/helper_files/{filename}.json")


def update_name(message_j, the_name):
    """Updates key name in json string with the_name."""
    message = json.loads(message_j)
    message["detail"]["name"] = the_name
    return json.dumps(message)


def tagtime(key: str, version: dict) -> datetime:
    """Given a key's version, will return the time of the event's creation."""
    if not "VersionId" in version:  # localstack weirdness?
        version["VersionId"] = "null"
    tagset = pytest.s3.get_object_tagging(
        Bucket=pytest.bucketname, Key=key, VersionId=version["VersionId"]
    )["TagSet"]
    logger.debug("tagset: %s", tagset)
    tag = [x for x in tagset if x["Key"] == "ssmbakTime"].pop()
    logger.debug("tag: %s", tag)
    utc_time = datetime.fromtimestamp(int(tag["Value"]), tz=timezone.utc)
    return utc_time


def get_tagset(key):
    """Returns the current tagset of an s3 key in a more readable format."""
    tagset = pytest.s3.get_object_tagging(Bucket=pytest.bucketname, Key=key)["TagSet"]
    nice_tagset = {x["Key"]: x["Value"] for x in tagset}
    logger.debug("get_tagset: %s", nice_tagset)
    return nice_tagset


def test_process_message():
    """Unit test process_message used by everything."""
    testo = slurp_helper("create")
    data = ssmbak.process_message(update_name(testo, name))
    assert data["name"] == name
    assert data["type"] == "String"
    assert data["operation"] == "Create"
    assert isinstance(data["time"], datetime)
    assert data["time"].tzinfo is not None
    assert data["time"].tzinfo.utcoffset(data["time"]) is not None


@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
def test_backup_create_root_pathkey(backup_source):
    """Tests for bug in ssm for root-level keys. See ssmbak.py for details"""
    noslash = pytest.test_path.lstrip("/").rstrip("/")
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()
    testo = slurp_helper("create")
    action = ssmbak.process_message(update_name(testo, noslash))
    backup_action = getattr(backup_source, "process_message")(
        update_name(testo, noslash)
    )
    new_stuff = helpers.prep(action)
    getattr(backup_source, "backup")(backup_action)
    version = pytest.s3.get_object(Bucket=pytest.bucketname, Key=action["name"])
    logger.debug("version: %s", version)
    assert version["ResponseMetadata"]["HTTPStatusCode"] == 200
    tagset = get_tagset(action["name"])
    assert tagset["ssmbakType"] == action["type"]
    stuff = version["Body"].read().decode("utf-8").strip()
    assert stuff == new_stuff["Value"]
    # not the best test, but cya
    taggy = tagtime(action["name"], version)
    logger.debug(taggy)
    assert taggy == datetime(2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc)


@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
@pytest.mark.parametrize("totest", ["create", "create_desc"])
def test_backup_create(backup_source, totest):
    """Test the backing up of an SSM Param Create event

    Parametrized for with/without a description.

    Parametrized for backing up with library or using localstack's
    lambda service (skipping if not local).
    """
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()
    testo = slurp_helper(totest)
    action = ssmbak.process_message(update_name(testo, name))
    backup_action = getattr(backup_source, "process_message")(update_name(testo, name))
    new_stuff = helpers.prep(action)
    getattr(backup_source, "backup")(backup_action)
    version = pytest.s3.get_object(Bucket=pytest.bucketname, Key=action["name"])
    logger.debug("version: %s", version)
    assert version["ResponseMetadata"]["HTTPStatusCode"] == 200
    tagset = get_tagset(action["name"])
    assert tagset["ssmbakType"] == action["type"]
    stuff = version["Body"].read().decode("utf-8").strip()
    assert stuff == new_stuff["Value"]
    # not the best test, but cya
    taggy = tagtime(action["name"], version)
    logger.debug(taggy)
    assert taggy == datetime(2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc)


def check_description(check_tagset: dict, action: dict) -> bool:
    """Compares description from action with the resulting tagset."""
    try:
        description = check_tagset["ssmbakDescription"]
    except KeyError:
        description = None
    try:
        action_description = action["description"]
    except KeyError:
        action_description = None
    assert description == action_description
    logger.debug("%s == %s", description, action_description)
    return True


# one from lib, one via local lambda container
@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
@pytest.mark.parametrize("totest", ["update_desc", "update", "update_secure"])
def test_backup_update(backup_source, totest):
    """Test the backing up of an SSM Param Update event

    Parametrized for with/without a description and with SecureString
    (SecureString might be redundant).

    Parametrized for backing up with library or using localstack's
    lambda service (skipping if not local).
    """
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()
    testo = slurp_helper(totest)
    action = ssmbak.process_message(update_name(testo, name))
    backup_action = getattr(backup_source, "process_message")(update_name(testo, name))
    new_stuff = helpers.prep(action)
    getattr(backup_source, "backup")(helpers.update_time(backup_action))
    now = datetime.now(tz=timezone.utc)
    logger.debug("now: %s", now)
    check = pytest.s3.get_object(Bucket=pytest.bucketname, Key=action["name"])
    check_tagset = get_tagset(action["name"])
    stuff = check["Body"].read().decode("utf-8").strip()
    assert stuff == new_stuff["Value"]
    assert check_tagset["ssmbakType"] == action["type"]
    assert check_description(check_tagset, action)
    taggy = tagtime(action["name"], check)
    logger.debug(taggy)
    diff = now - taggy
    assert diff.seconds < 60


@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
def test_backup_delete(backup_source):
    """Test the backing up of an SSM Param Delete event

    Parametrized for backing up with library or using localstack's
    lambda service (skipping if not local).
    """
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()
    testo = slurp_helper("delete")
    backup_action = getattr(backup_source, "process_message")(update_name(testo, name))
    action = ssmbak.process_message(update_name(testo, name))
    helpers.prep(action)
    getattr(backup_source, "backup")(backup_action)
    ssmbak.backup(action)
    there = True
    try:
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=action["name"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            there = False
    assert not there


@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
def test_backup_create_noparam(backup_source):
    """I can't remember why I did this."""
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()
    testo = slurp_helper("create")
    action = ssmbak.process_message(update_name(testo, name))
    backup_action = getattr(backup_source, "process_message")(update_name(testo, name))
    logger.debug("action: %s", action)
    helpers.prep(action)
    pytest.ssm.delete_parameter(Name=action["name"])
    res = getattr(backup_source, "backup")(backup_action)
    if backup_source == local_lambda:
        # this means nothing with localstack
        assert res.status_code == 200
