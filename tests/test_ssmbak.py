"""Test suite for the lambda function, both lib and actual lambda (localstack)."""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from ssmbak.backup import ssmbak
from ssmbak.restore.actions import ParamPath

# pytype bug https://google.github.io/pytype/errors.html#pyi-error
from tests import helpers, local_lambda

logger = logging.getLogger(__name__)
NAME = f"{pytest.test_path}/{helpers.rando()}"


def slurp_helper(filename):
    """Slurps up content of helper file with filename."""
    return Path(f"{Path(__file__).parent}/helper_files/{filename}.json").read_text(
        encoding="utf-8"
    )


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


def test_sanitize_tag_value():
    """Test _sanitize_tag_value sanitizes and truncates tag values for S3."""
    # Test that parentheses are stripped
    result = ssmbak._sanitize_tag_value("ssmbak bucket (auto-discovered)")  # pylint: disable=protected-access
    assert result == "ssmbak bucket auto-discovered"

    # Test that allowed special chars are preserved
    result = ssmbak._sanitize_tag_value("test + value = good_result")  # pylint: disable=protected-access
    assert result == "test + value = good_result"

    # Test truncation to 256 chars
    long_string = "a" * 300
    result = ssmbak._sanitize_tag_value(long_string)  # pylint: disable=protected-access
    assert len(result) == 256
    assert result == "a" * 256


def test_process_message():
    """Unit test process_message used by everything."""
    testo = slurp_helper("create")
    data = ssmbak.process_message(update_name(testo, NAME))
    assert data["name"] == NAME
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
    action = ssmbak.process_message(update_name(testo, NAME))
    backup_action = getattr(backup_source, "process_message")(update_name(testo, NAME))
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
    action = ssmbak.process_message(update_name(testo, NAME))
    backup_action = getattr(backup_source, "process_message")(update_name(testo, NAME))
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
    backup_action = getattr(backup_source, "process_message")(update_name(testo, NAME))
    action = ssmbak.process_message(update_name(testo, NAME))
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
    action = ssmbak.process_message(update_name(testo, NAME))
    backup_action = getattr(backup_source, "process_message")(update_name(testo, NAME))
    logger.debug("action: %s", action)
    helpers.prep(action)
    pytest.ssm.delete_parameter(Name=action["name"])
    res = getattr(backup_source, "backup")(backup_action)
    if backup_source == local_lambda:
        # this means nothing with localstack
        assert res.status_code == 200


# Tests for preview/restore filtering to only changed parameters


def test_preview_excludes_unchanged():
    """Test that preview excludes parameters that haven't changed since backup."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a parameter
    message = helpers.prep_message(name, "Create", "String", description=True)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Delete parameter from SSM, then preview should show it needs to be created
    pytest.ssm.delete_parameter(Name=name)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name

    # Now set SSM to match backup state exactly
    pytest.ssm.put_parameter(**initial_param)

    # Preview again - should be empty (no changes needed)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 0


def test_preview_includes_value_change():
    """Test that preview includes parameters whose value changed."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a parameter
    message = helpers.prep_message(name, "Create", "String", description=True)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Change the value in SSM
    pytest.ssm.put_parameter(
        Name=name, Value="different-value", Type="String", Overwrite=True
    )

    # Preview should show the parameter (value differs)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name
    assert previews[0]["Value"] == initial_param["Value"]


def test_preview_includes_type_change():
    """Test that preview includes parameters whose type changed."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a String parameter
    message = helpers.prep_message(name, "Create", "String", description=False)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Change to StringList in SSM
    pytest.ssm.put_parameter(
        Name=name,
        Value=initial_param["Value"],
        Type="StringList",
        Overwrite=True,
    )

    # Preview should show the parameter (type differs)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name
    assert previews[0]["Type"] == "String"


def test_preview_includes_description_change():
    """Test that preview includes parameters whose description changed."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup with description
    message = helpers.prep_message(name, "Create", "String", description=True)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Change description in SSM
    pytest.ssm.put_parameter(
        Name=name,
        Value=initial_param["Value"],
        Type=initial_param["Type"],
        Description="different description",
        Overwrite=True,
    )

    # Preview should show the parameter (description differs)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name
    assert previews[0]["Description"] == "fancy description"


def test_preview_includes_deleted_parameter():
    """Test that preview includes parameters that were deleted since backup."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a parameter
    message = helpers.prep_message(name, "Create", "String", description=True)
    action = ssmbak.process_message(message)
    helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Delete the parameter from SSM
    pytest.ssm.delete_parameter(Name=name)

    # Preview should show the parameter (needs to be restored)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name


def test_preview_excludes_created_parameter():
    """Test that preview excludes parameters created after backup time."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Create parameter in SSM but don't back it up
    pytest.ssm.put_parameter(
        Name=name, Value="new-value", Type="String", Overwrite=False
    )

    # Preview should be empty (param didn't exist at checktime)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 0


def test_preview_excludes_deleted_at_checktime_still_deleted():
    """Test that deleted-at-checktime, still-deleted params are excluded (no-op)."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create, backup, delete, backup delete
    message = helpers.prep_message(name, "Create", "String", description=False)
    action = ssmbak.process_message(message)
    helpers.prep(action)
    ssmbak.backup(action)

    # Delete and backup the deletion
    delete_message = helpers.prep_message(name, "Delete", "String", description=False)
    delete_action = ssmbak.process_message(delete_message)
    helpers.prep(delete_action)
    ssmbak.backup(helpers.update_time(delete_action))

    time.sleep(1)
    checktime = datetime.now(tz=timezone.utc)
    time.sleep(1)

    # Ensure parameter doesn't exist in SSM
    try:
        pytest.ssm.delete_parameter(Name=name)
    except ClientError:
        pass  # Already deleted

    # Preview should be empty (deleted then, still deleted now = no-op)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 0


def test_preview_includes_deleted_at_checktime_recreated():
    """Test that deleted-at-checktime but now-exists params are included."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create, backup, delete, backup delete
    message = helpers.prep_message(name, "Create", "String", description=False)
    action = ssmbak.process_message(message)
    helpers.prep(action)
    ssmbak.backup(action)

    # Delete and backup the deletion
    delete_message = helpers.prep_message(name, "Delete", "String", description=False)
    delete_action = ssmbak.process_message(delete_message)
    helpers.prep(delete_action)
    ssmbak.backup(helpers.update_time(delete_action))

    time.sleep(1)
    checktime = datetime.now(tz=timezone.utc)
    time.sleep(1)

    # Recreate parameter in SSM
    pytest.ssm.put_parameter(
        Name=name, Value="recreated-value", Type="String", Overwrite=True
    )

    # Preview should show deletion (was deleted at checktime, exists now)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name
    assert previews[0].get("Deleted") is True


def test_preview_mixed_batch():
    """Test recursive path with mix of changed and unchanged parameters."""
    # Create multiple parameters with different states
    names = [f"{pytest.test_path}/{helpers.rando()}" for _ in range(5)]
    params = {}

    # Create and backup all
    for name in names:
        message = helpers.prep_message(name, "Create", "String", description=True)
        action = ssmbak.process_message(message)
        param = helpers.prep(action)
        params[name] = param
        ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # names[0]: unchanged
    # names[1]: value changed
    # names[2]: type changed
    # names[3]: description changed
    # names[4]: deleted

    # Keep names[0] unchanged
    pytest.ssm.put_parameter(**params[names[0]])

    # Change value on names[1]
    pytest.ssm.put_parameter(
        Name=names[1],
        Value="different-value",
        Type=params[names[1]]["Type"],
        Description=params[names[1]]["Description"],
        Overwrite=True,
    )

    # Change type on names[2]
    pytest.ssm.put_parameter(
        Name=names[2],
        Value=params[names[2]]["Value"],
        Type="StringList",
        Overwrite=True,
    )

    # Change description on names[3]
    pytest.ssm.put_parameter(
        Name=names[3],
        Value=params[names[3]]["Value"],
        Type=params[names[3]]["Type"],
        Description="new description",
        Overwrite=True,
    )

    # Delete names[4]
    pytest.ssm.delete_parameter(Name=names[4])

    # Preview should only show the 4 changed parameters
    path = ParamPath(
        f"{pytest.test_path}/", checktime, pytest.region, pytest.bucketname, recurse=True
    )
    previews = path.preview()
    preview_names = [p["Name"] for p in previews]

    assert len(previews) == 4
    assert names[0] not in preview_names  # unchanged
    assert names[1] in preview_names  # value changed
    assert names[2] in preview_names  # type changed
    assert names[3] in preview_names  # description changed
    assert names[4] in preview_names  # deleted


def test_preview_securestring_comparison():
    """Test that SecureString values are compared correctly."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a SecureString parameter
    message = helpers.prep_message(name, "Create", "SecureString", description=True)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Set SSM to match backup (unchanged)
    pytest.ssm.put_parameter(**initial_param)

    # Preview should be empty (no changes)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 0

    # Change the value
    pytest.ssm.put_parameter(
        Name=name,
        Value="different-secure-value",
        Type="SecureString",
        Overwrite=True,
    )

    # Preview should now show it
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name


def test_restore_skips_unchanged():
    """Test that restore skips unchanged parameters."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a parameter
    message = helpers.prep_message(name, "Create", "String", description=True)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Set SSM to match backup state exactly
    pytest.ssm.put_parameter(**initial_param)

    # Get version before restore
    param_before = pytest.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    version_before = param_before["Version"]

    # Restore should return empty list (no changes)
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    restored = path.restore()
    assert len(restored) == 0

    # Verify SSM version didn't change (parameter wasn't touched)
    param_after = pytest.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    version_after = param_after["Version"]
    assert version_before == version_after


def test_restore_applies_changes():
    """Test that restore applies actual changes."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    # Create and backup a parameter
    message = helpers.prep_message(name, "Create", "String", description=True)
    action = ssmbak.process_message(message)
    initial_param = helpers.prep(action)
    ssmbak.backup(action)

    checktime = helpers.str2datetime("2023-08-31T09:48:00")

    # Change the value in SSM
    pytest.ssm.put_parameter(
        Name=name,
        Value="changed-value",
        Type=initial_param["Type"],
        Description=initial_param["Description"],
        Overwrite=True,
    )

    # Restore should apply changes
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname)
    restored = path.restore()
    assert len(restored) == 1

    # Verify SSM was restored to original value
    param = pytest.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    assert param["Value"] == initial_param["Value"]
