"""The main restore test."""

import logging
from datetime import datetime, timezone

import pytest

from ssmbak.restore.actions import ParamPath
from tests import helpers

logger = logging.getLogger(__name__)


def test_key_not_path():
    """Makes sure a key doesn't return all keys that start with it"""
    name = f"{pytest.test_path}/{helpers.rando()}"
    similar_name = f"{name}a"
    initial_params = helpers.create_and_check([name, similar_name])
    helpers.update_and_check([name])
    in_between = helpers.str2datetime("2023-08-31T09:48:00")
    key = ParamPath(
        name,
        in_between,
        pytest.region,
        pytest.bucketname,
    )
    previews = key.preview()
    assert [x["Name"] for x in previews] == [name]
    helpers.compare_previews_with_params(previews, initial_params)


# Shows the "bug" in ssm set
# def test_key_not_path_root():
#     """Makes sure a key doesn't return all keys that start with it"""
#     name = pytest.test_path.lstrip("/")
#     logger.warning(name)
#     initial_params = helpers.create_and_check([name])
#     in_between = helpers.str2datetime("2023-08-31T09:48:00")
#     key = Path(
#         name,
#         in_between,
#         pytest.region,
#         pytest.bucketname,
#     )
#     logger.warning(key)
#     previews = key.preview()
#     assert [x["Name"] for x in previews] == [name]


def test_key():
    """Tests just one key instead of a path.

    Under the hood they're the same.
    """
    name = f"{pytest.test_path}/{helpers.rando()}"
    initial_params = helpers.create_and_check([name])
    helpers.update_and_check([name])
    in_between = helpers.str2datetime("2023-08-31T09:48:00")
    key = ParamPath(
        name,
        in_between,
        pytest.region,
        pytest.bucketname,
    )
    logger.info("preview")
    previews = key.preview()
    assert [x["Name"] for x in previews] == [name]
    helpers.compare_previews_with_params(previews, initial_params)
    assert {x["Modified"] for x in previews} == {
        datetime(2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc)
    }
    logger.info("restore, which uses preview")
    assert key.restore() == previews
    helpers.check_param(name, initial_params)
    # deleted
    deltime, deleted_params = helpers.delete_params([name])
    logger.info("deleted_params %s", deleted_params)
    logger.info("%s deleted, deltime: %s", name, deltime)
    key = ParamPath(
        name,
        deltime,
        pytest.region,
        pytest.bucketname,
    )
    logger.info("preview")
    previews = key.preview()
    assert [x["Name"] for x in previews] == [name]
    logger.info(key)
    logger.info(helpers.pretty(previews))
    assert [x["Name"] for x in previews if "Deleted" in x and x["Deleted"] is True] == [
        name
    ]
    # restore with dels
    key.restore()
    with pytest.raises(Exception):
        # pylint: disable=expression-not-assigned
        pytest.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]


def test_exact_time_match():
    """Test that backups at exact checktime are included.

    This tests the edge case where restore time equals backup event time.
    The backup event time is hardcoded in helpers.prep_message() as 2022-08-03T21:09:31.
    This test verifies that using that exact time as checktime includes the backup.
    """
    name = f"{pytest.test_path}/{helpers.rando()}"
    initial_params = helpers.create_and_check([name])

    # Modify the parameter to create a difference from the backup
    pytest.ssm.put_parameter(
        Name=name,
        Value="modified-value",
        Type=initial_params[name]["Type"],
        Overwrite=True,
    )

    # Use the EXACT backup time (hardcoded in prep_message)
    exact_time = helpers.str2datetime("2022-08-03T21:09:31")

    key = ParamPath(name, exact_time, pytest.region, pytest.bucketname)
    previews = key.preview()

    # Should find the backup that occurred at this exact time
    assert len(previews) == 1
    assert previews[0]["Name"] == name
    helpers.compare_previews_with_params(previews, initial_params)
    assert previews[0]["Modified"] == datetime(
        2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc
    )


def test_tz_plus():
    """Originally for tz test, but other bits got added."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    initial_params = helpers.create_and_check([name])
    helpers.update_and_check([name])
    just_after = helpers.str2datetime("2022-08-03T21:10:00")
    path = ParamPath(name, just_after, pytest.region, pytest.bucketname)
    version = path.get_latest_version(name)
    logger.debug(helpers.pretty(version))
    preview = path.preview()[0]
    kwargs = {
        "Name": name,
        "Value": initial_params[name]["Value"],
        "Type": initial_params[name]["Type"],
        "Modified": datetime(2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc),
    }
    if "Description" in initial_params[name]:
        kwargs["Description"] = initial_params[name]["Description"]
    assert preview == kwargs
    in_between = helpers.str2datetime("2023-08-31T09:48:00")
    path = ParamPath(name, in_between, pytest.region, pytest.bucketname)
    logger.debug(helpers.pretty(preview))
    path.restore()
    too_early = helpers.str2datetime("1999-08-31T09:48:00")
    path = ParamPath(name, too_early, pytest.region, pytest.bucketname)
    assert path.get_latest_version(name) is None
