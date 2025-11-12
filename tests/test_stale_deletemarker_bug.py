"""Test to reproduce bug where stale DeleteMarkers override newer Versions.

This reproduces the real-world scenario seen in CLI tutorial tests:
- Old test run left delete markers in S3 (e.g., 05:23:42)
- New test creates parameters and backs them up (e.g., 05:32:10)
- Query at time after new backup (e.g., 05:33:15)
- BUG: Returns old delete marker instead of new backup

The root cause is in the restore query logic which doesn't properly
filter versions by timestamp before selecting the "most recent" one.
"""

# pylint: skip-file

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import pytest

from ssmbak.backup import ssmbak
from ssmbak.restore.actions import ParamPath
from tests import helpers, local_lambda

logger = logging.getLogger(__name__)


@pytest.mark.parametrize("backup_source", [local_lambda, ssmbak])
def test_stale_delete_marker_should_not_override_newer_backup(backup_source):
    """Test that old delete markers don't hide newer backups.

    Timeline (simulating real CLI tutorial scenario):
    1. T1: Delete parameter (creates DeleteMarker with event time T1, e.g., 05:23:42)
       This happens LATER in wall-clock time but gets EARLIER event time
    2. T2: Create and backup parameter with value "new" (event time T2, e.g., 05:32:10)
       This happens EARLIER in wall-clock time but gets LATER event time
    3. T3: Query checktime (e.g., 05:33:15) where T3 > T2 > T1

    Expected: Should find "new" backup (event time T2)
    Actual Bug: Returns delete marker (event time T1) because it has later LastModified
    """
    if backup_source == local_lambda and not pytest.check_local():
        pytest.skip()

    name = f"{pytest.test_path}/{helpers.rando()}"

    # Define event times first (simulating old vs new test runs)
    # T1 is old delete (05:23:42 in real scenario)
    # T2 is new create (05:32:10 in real scenario)
    # T3 is query time (05:33:15 in real scenario)
    base_time = datetime.now(tz=timezone.utc)
    t1_delete_event = base_time + timedelta(seconds=10)  # Event time for delete
    t2_create_event = base_time + timedelta(seconds=20)  # Event time for create (LATER)
    t3_query = base_time + timedelta(seconds=30)  # Query time

    logger.info("Timeline:")
    logger.info("  T1 (delete event time): %s", t1_delete_event)
    logger.info("  T2 (create event time): %s", t2_create_event)
    logger.info("  T3 (query checktime): %s", t3_query)

    # Step 1: Create backup FIRST (early LastModified, but LATE event time T2)
    logger.info("Step 1: Creating backup with event time T2 (LATER event time)")
    message = helpers.prep_message(name, "Create", "String", description=False)
    backup_action = getattr(backup_source, "process_message")(message)
    # Set event time to T2 (later)
    if "Records" in backup_action:  # local_lambda
        body = json.loads(backup_action["Records"][0]["body"])
        body["time"] = t2_create_event.strftime("%Y-%m-%dT%H:%M:%SZ")
        backup_action["Records"][0]["body"] = json.dumps(body)
    else:  # ssmbak library
        backup_action["time"] = t2_create_event
    pytest.ssm.put_parameter(Name=name, Value="new", Type="String", Overwrite=True)
    getattr(backup_source, "backup")(backup_action)
    time.sleep(2)  # Ensure time difference
    logger.info("Backup created: LastModified=early, event time=T2 (late)")

    # Step 2: Create delete marker SECOND (late LastModified, but EARLY event time T1)
    # This simulates old test leaving delete markers that were written to S3 later
    # but have earlier event timestamps
    logger.info(
        "Step 2: Creating delete marker with event time T1 (EARLIER event time)"
    )
    pytest.ssm.delete_parameter(Name=name)
    delete_message = helpers.prep_message(name, "Delete", "String")
    delete_backup_action = getattr(backup_source, "process_message")(delete_message)
    # Set event time to T1 (earlier than backup's T2)
    if "Records" in delete_backup_action:  # local_lambda
        body = json.loads(delete_backup_action["Records"][0]["body"])
        body["time"] = t1_delete_event.strftime("%Y-%m-%dT%H:%M:%SZ")
        delete_backup_action["Records"][0]["body"] = json.dumps(body)
    else:  # ssmbak library
        delete_backup_action["time"] = t1_delete_event
    getattr(backup_source, "backup")(delete_backup_action)
    time.sleep(1)
    logger.info("Delete marker created: LastModified=late, event time=T1 (early)")

    # Step 3: Query at T3 - THIS IS WHERE THE BUG MANIFESTS
    logger.info("Step 3: Querying at T3 (both versions should pass filter)")
    key = ParamPath(name, t3_query, pytest.region, pytest.bucketname)
    previews = key.preview()
    logger.info("Previews at T3: %s", helpers.pretty(previews))

    # Both delete (T1) and backup (T2) should pass the filter since T1 < T3 and T2 < T3
    # Expected: Should return backup (T2) since it has the LATEST event time < T3
    # Bug: Returns delete marker (T1) because it has later LastModified

    assert len(previews) == 1
    preview = previews[0]
    assert preview["Name"] == name

    # The critical assertion - should NOT be deleted
    assert "Deleted" not in preview or preview.get("Deleted") is not True, (
        f"BUG: Query at T3 should return backup (event time T2={t2_create_event}), "
        f"but got delete marker (event time T1={t1_delete_event}). "
        f"Both pass checktime filter (T3={t3_query}), but code picks wrong one based on LastModified."
    )

    # Should have the new value
    assert (
        preview["Value"] == "new"
    ), f"Expected 'new' value at T3, got '{preview.get('Value')}'"
    assert preview["Type"] == "String"
