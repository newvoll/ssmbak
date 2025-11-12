"""The main restore test."""

import logging
from datetime import datetime, timezone

import pytest

from ssmbak.restore.actions import ParamPath
from tests import helpers

logger = logging.getLogger(__name__)


def get_names(recurse):
    """Generates a bunch of key names, deeper ones for recurse."""
    names = [f"{pytest.test_path}/{helpers.rando()}" for x in range(11)]
    if recurse:
        names.extend(f"{pytest.test_path}/foofers/{helpers.rando()}" for x in range(11))
    return names


def test_noparams():
    """Make sure doesn't bomb when no params are there_now."""
    in_between = helpers.str2datetime("2023-08-31T09:48:00")
    path = ParamPath(
        f"{pytest.test_path}/",
        in_between,
        pytest.region,
        pytest.bucketname,
    )
    logger.warning(path)
    path.preview()


@pytest.mark.parametrize("recurse", [True, False])
def test_path(recurse):
    """Parametrized for recurse and not.

    Didn't make sense to split up in favor of continuously reusing state.
    """
    names = get_names(recurse)
    logger.info("create backups and params")
    initial_params = helpers.create_and_check(names)
    # set a path that's also a key but don't include
    helpers.create_and_check([pytest.test_path])
    logger.info("update some")
    helpers.update_and_check(names)
    # check that restore() returns originals
    in_between = helpers.str2datetime("2023-08-31T09:48:00")
    path = ParamPath(
        f"{pytest.test_path}/",
        in_between,
        pytest.region,
        pytest.bucketname,
        recurse=recurse,
    )
    logger.info("preview")
    previews = path.preview()
    assert len(previews) == len(names)
    assert [x["Name"] for x in previews] == sorted(names)
    helpers.compare_previews_with_params(previews, initial_params)
    assert {x["Modified"] for x in previews} == {
        datetime(2022, 8, 3, 21, 9, 31, tzinfo=timezone.utc)
    }
    logger.info("restore, which uses preview")
    assert path.restore() == previews
    for name in names:
        helpers.check_param(name, initial_params)
    n, to_deletes = helpers.delete_some(3, names)
    logger.info("delete %s (%s)", to_deletes, n)
    ## for deleted, check that it worked
    deltime, deleted_params = helpers.delete_params(to_deletes)
    logger.debug("deleted_params %s", deleted_params)
    logger.info("same path, new object with deltime: %s", deltime)
    path = ParamPath(
        f"{pytest.test_path}/",
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
    ## check no trailing slash before restore
    logger.warning("slashtest")
    path_noslash = ParamPath(
        f"{pytest.test_path}",
        in_between,
        pytest.region,
        pytest.bucketname,
        recurse=recurse,
    )
    previews = path_noslash.preview()
    logger.warning(helpers.pretty(previews))
    assert len(previews) == 1
    # restore with dels
    path.restore()
    for name in to_deletes:
        with pytest.raises(Exception):
            # pylint: disable=expression-not-assigned
            pytest.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    # helpers.check_classvar_counts(
    #     {
    #         "tags": len(names) * 3,
    #         "versions": 2,
    #         "version_objects": len(names) * 2 - n,
    #     }
    # )
