"""Restore must enforce point-in-time state for tracked params."""

import logging

import pytest
from botocore.exceptions import ClientError

from ssmbak.backup import ssmbak
from ssmbak.restore.actions import ParamPath
from tests import helpers

logger = logging.getLogger(__name__)


def test_restore_deletes_param_created_after_checktime():
    """Param created+backed-up at T1, restored to T0 < T1, must be deleted from SSM."""
    name = f"{pytest.test_path}/{helpers.rando()}"

    # T1 is the hardcoded event time in helpers.prep_message ("2022-08-03T21:09:31Z").
    message = helpers.prep_message(name, "Create", "String", description=False)
    action = ssmbak.process_message(message)
    helpers.prep(action)
    ssmbak.backup(action)

    # Sanity: tracked in both SSM and S3.
    pytest.ssm.get_parameter(Name=name, WithDecryption=True)
    pytest.s3.get_object(Bucket=pytest.bucketname, Key=name)

    # Restore to T0 < T1.
    checktime = helpers.str2datetime("2022-08-01T00:00:00")
    path = ParamPath(name, checktime, pytest.region, pytest.bucketname, recurse=False)

    previews = path.preview()
    assert len(previews) == 1
    assert previews[0]["Name"] == name
    assert previews[0].get("Deleted") is True

    path.restore()

    with pytest.raises(ClientError) as exc:
        pytest.ssm.get_parameter(Name=name, WithDecryption=True)
    assert exc.value.response["Error"]["Code"] == "ParameterNotFound"
