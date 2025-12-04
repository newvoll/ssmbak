"""Test to reproduce the DeleteMarker bug when a parameter is recreated."""

# pylint: skip-file

import logging
import time
from datetime import datetime, timezone

import pytest

from ssmbak.backup import ssmbak
from ssmbak.restore.actions import ParamPath
from tests import helpers, local_lambda

logger = logging.getLogger(__name__)


@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
def test_recreated_parameter_after_delete(backup_source):
    """Tests timestamp-based filtering for DeleteMarkers vs backup Versions.

    Timeline:
    1. T1: Create parameter with value "initial"
    2. T2: Delete parameter (creates DeleteMarker in S3)
    3. T3: Recreate parameter with value "recreated"

    Tests queries at three different checktimes:
    - Before deletion (T1+1s): Should return "initial" value
    - After delete, before recreate (T2+1s): Should return Deleted=True
    - After recreation (T3+1s): Should return "recreated" value

    The bug is in aws.py:289-312 where DeleteMarkers are processed before
    regular Versions, and the first matching version for each Key blocks
    all subsequent versions from being considered, regardless of timestamps.
    """
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()

    name = f"{pytest.test_path}/{helpers.rando()}"

    # Step 1: Create initial parameter and capture timestamp
    logger.info("Creating initial parameter: %s", name)
    message = helpers.prep_message(name, "Create", "String", description=False)
    action = ssmbak.process_message(message)
    backup_action = getattr(backup_source, "process_message")(message)
    pytest.ssm.put_parameter(Name=name, Value="initial", Type="String", Overwrite=True)
    getattr(backup_source, "backup")(helpers.update_time(backup_action))
    time.sleep(1)
    t1 = datetime.now(tz=timezone.utc)
    logger.info("T1 (after create): %s", t1)

    # Sleep to ensure time difference
    time.sleep(2)

    # Step 2: Delete the parameter and capture timestamp
    logger.info("Deleting parameter: %s", name)
    pytest.ssm.delete_parameter(Name=name)
    delete_message = helpers.prep_message(name, "Delete", "String")
    delete_action = ssmbak.process_message(delete_message)
    delete_action = helpers.update_time(delete_action)
    delete_backup_action = getattr(backup_source, "process_message")(delete_message)
    getattr(backup_source, "backup")(helpers.update_time(delete_backup_action))
    time.sleep(1)
    t2 = datetime.now(tz=timezone.utc)
    logger.info("T2 (after delete): %s", t2)

    # Sleep to ensure time difference
    time.sleep(2)

    # Step 3: Recreate the parameter with new value and capture timestamp
    logger.info("Recreating parameter with new value: %s", name)
    recreate_message = helpers.prep_message(name, "Create", "String", description=False)
    recreate_action = ssmbak.process_message(recreate_message)
    recreate_action = helpers.update_time(recreate_action)
    recreate_backup_action = getattr(backup_source, "process_message")(recreate_message)
    pytest.ssm.put_parameter(
        Name=name, Value="recreated", Type="String", Overwrite=True
    )
    getattr(backup_source, "backup")(helpers.update_time(recreate_backup_action))
    time.sleep(1)
    t3 = datetime.now(tz=timezone.utc)
    logger.info("T3 (after recreate): %s", t3)

    # Modify SSM to differ from all three backup states to ensure preview includes them
    pytest.ssm.put_parameter(
        Name=name, Value="current-modified", Type="String", Overwrite=True
    )

    # Test 1: Query BEFORE deletion - should see "initial" value
    logger.info("Test 1: Querying at T1 (before deletion)")
    key1 = ParamPath(name, t1, pytest.region, pytest.bucketname)
    previews1 = key1.preview()
    logger.info("Previews at T1: %s", helpers.pretty(previews1))

    assert len(previews1) == 1
    preview1 = previews1[0]
    assert preview1["Name"] == name
    assert (
        "Deleted" not in preview1 or preview1.get("Deleted") is not True
    ), "Parameter should not be deleted at T1"
    assert (
        preview1["Value"] == "initial"
    ), f"Expected 'initial' at T1, got '{preview1.get('Value')}'"
    assert preview1["Type"] == "String"

    # Test 2: Query AFTER delete but BEFORE recreate - should see Deleted=True
    logger.info("Test 2: Querying at T2 (after delete, before recreate)")
    key2 = ParamPath(name, t2, pytest.region, pytest.bucketname)
    previews2 = key2.preview()
    logger.info("Previews at T2: %s", helpers.pretty(previews2))

    assert len(previews2) == 1
    preview2 = previews2[0]
    assert preview2["Name"] == name
    assert (
        preview2.get("Deleted") is True
    ), "Parameter should be marked as deleted at T2"

    # Test 3: Query AFTER recreation - should see "recreated" value
    logger.info("Test 3: Querying at T3 (after recreation)")
    key3 = ParamPath(name, t3, pytest.region, pytest.bucketname)
    previews3 = key3.preview()
    logger.info("Previews at T3: %s", helpers.pretty(previews3))

    assert len(previews3) == 1
    preview3 = previews3[0]
    assert preview3["Name"] == name
    assert (
        "Deleted" not in preview3 or preview3.get("Deleted") is not True
    ), "Parameter should not be deleted at T3 - it was recreated!"
    assert (
        preview3["Value"] == "recreated"
    ), f"Expected 'recreated' at T3, got '{preview3.get('Value')}'"
    assert preview3["Type"] == "String"
