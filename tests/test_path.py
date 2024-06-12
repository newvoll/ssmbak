"""The main restore test."""

import logging
from datetime import datetime, timezone

import pytest

from ssmbak.restore.actions import Path
from tests import helpers

logger = logging.getLogger(__name__)


def get_names(recurse):
    """Generates a bunch of key names, deeper ones for recurse."""
    names = [f"{pytest.test_path}/{helpers.rando()}" for x in range(11)]
    if recurse:
        names.extend(f"{pytest.test_path}/foofers/{helpers.rando()}" for x in range(11))
    return names


@pytest.mark.parametrize("recurse", [True, False])
def test_path(recurse):
    """Parametrized for recurse and not.

    Didn't make sense to split up in favor of continuously reusing state.
    """
    names = get_names(recurse)
    logger.info("create backups and params")
    initial_params = helpers.create_and_check(names)
    logger.info("update some")
    helpers.update_and_check(names)
    # check that restore() returns updated
    in_between = helpers.str2datetime("2023-08-31T09:48:00")
    path = Path(
        pytest.test_path,
        in_between,
        pytest.region,
        pytest.bucketname,
        recurse=recurse,
    )
    logger.info("preview")
    previews = path.preview()
    assert sorted([x["Name"] for x in previews]) == sorted(names)
    helpers.compare_previews_with_params(previews, initial_params)
    assert {x["Modified"] for x in previews} == {
        datetime(2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc)
    }
    logger.info("restore, which uses preview")
    assert path.restore() == previews
    for name in names:
        ssm_param = pytest.ssm.get_parameter(Name=name, WithDecryption=True)[
            "Parameter"
        ]
        assert ssm_param["Value"] == initial_params[ssm_param["Name"]]["Value"]
        assert ssm_param["Type"] == initial_params[ssm_param["Name"]]["Type"]
        param_desc = pytest.ssm.describe_parameters(
            ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}]
        )["Parameters"][0]
        if "Description" in initial_params[ssm_param["Name"]]:
            assert (
                param_desc["Description"]
                == initial_params[ssm_param["Name"]]["Description"]
            )
    n, to_deletes = helpers.delete_some(3, names)
    logger.info("delete %s", to_deletes)
    ## for deleted, check that it worked
    deltime, deleted_params = helpers.delete_params(to_deletes)
    logger.debug("deleted_params %s", deleted_params)
    logger.info("same path, new object with deltime: %s", deltime)
    path = Path(
        pytest.test_path,
        deltime,
        pytest.region,
        pytest.bucketname,
        recurse=recurse,
    )
    logger.info("preview")
    previews = path.preview()
    assert sorted([x["Name"] for x in previews]) == sorted(names)
    assert sorted(
        [x["Name"] for x in previews if "Deleted" in x and x["Deleted"] is True]
    ) == sorted(to_deletes)
    ## check trailing slash before restore
    path_slash = Path(
        f"{pytest.test_path}/",
        in_between,
        pytest.region,
        pytest.bucketname,
        recurse=recurse,
    )
    assert path_slash.name == path.name
    # restore with dels
    path.restore()
    for name in to_deletes:
        with pytest.raises(Exception):
            # pylint: disable=expression-not-assigned
            pytest.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    helpers.check_classvar_counts(
        {
            "tags": len(names) * 3,
            "versions": 2,
            "version_objects": len(names) * 2 - n,
        }
    )


def test_one_key_and_tz():
    """Originally for tz test, but other bits got added."""
    name = f"{pytest.test_path}/{helpers.rando()}"
    initial_params = helpers.create_and_check([name])
    helpers.update_and_check([name])
    just_after = helpers.str2datetime("2022-08-03T21:10:00")
    path = Path(name, just_after, pytest.region, pytest.bucketname)
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
    path = Path(name, in_between, pytest.region, pytest.bucketname)
    logger.debug(helpers.pretty(preview))
    path.restore()
    too_early = helpers.str2datetime("1999-08-31T09:48:00")
    path = Path(name, too_early, pytest.region, pytest.bucketname)
    assert path.get_latest_version(name) == {}
