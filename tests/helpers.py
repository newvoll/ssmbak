"""Abstracted functions to make test(s) more readable.

There used to be components other than Path, for which this proved
immensely useful.
"""

import json
import logging
import pprint
import random
import string
import time
from datetime import datetime, timedelta, timezone

import pytest

from ssmbak.backup import ssmbak
from ssmbak.restore.aws import Resource

pp = pprint.PrettyPrinter(indent=4)
logger = logging.getLogger(__name__)


def pretty(thingy):
    """Quick pp.pprint."""
    return f"\n{pp.pformat(thingy)}\n"


def slurp(filename):
    """Quick file contents to string."""
    with open(filename, encoding="utf-8") as x:
        f = x.read()
    return f


def str2datetime(checktime):
    """For ease of checktime creations."""
    return datetime.strptime(checktime, "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def update_time(action: dict) -> dict:
    """Updates time of an action to be processed by ssmabk."""
    if "Records" in action:  # it's mock AWS
        body = json.loads(action["Records"][0]["body"])
        now = datetime.now(tz=timezone.utc)
        body["time"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        action["Records"][0]["body"] = json.dumps(body)
    else:
        action["time"] = datetime.now(tz=timezone.utc)
    return action


def rando(size=6, chars=string.ascii_uppercase + string.digits) -> str:
    """Quickly generates a random string so we don't hard-code keys in tests."""
    return "".join(random.choice(chars) for _ in range(size))


def prep(action: dict) -> dict:
    """Actually put the ssm var before trying to back it up."""
    value = rando()
    kwargs = {
        "Name": action["name"],
        "Value": value,
        "Type": action["type"],
        "Overwrite": True,
    }
    if "description" in action:
        kwargs["Description"] = action["description"]
    pytest.ssm.put_parameter(**kwargs)
    return kwargs


def update_description(action: dict, msg: str) -> dict:
    """Update desecription of backup action."""
    logger.debug("UT action: %s", action)
    if "description" in action:
        action["description"] = msg
    return action


def update_type(action: dict) -> dict:
    """Update Type of backup action."""
    logger.debug("UT action: %s", action)
    action["type"] = "StringList"
    return action


def prep_message(name, op, what_type, description=True):
    """Fill in boilerplate event message with what's needed for a test."""
    message = {
        "version": "0",
        "id": "b29ebe75-717a-78b4-1562-4a247cdd4105",
        "detail-type": "Parameter Store Change",
        "source": "aws.ssm",
        "account": "000000000000",
        "time": "2022-08-03T21:09:31Z",
        "region": "us-east-1",
        "resources": [f"arn:aws:ssm:us-east-1:000000000000:parameter/{name}"],
        "detail": {
            "name": name,
            "type": what_type,
            "operation": op,
        },
    }
    if description:
        message["detail"]["description"] = "fancy description"
    return json.dumps(message)


def delete_params(names):
    """Chooses random elements of names to delete.

    Marks the time after deletion (deltime), then updates them to make
    sure ensuing preview/restore uses deltime accurately.

    time.sleep rather than manipulating with
    datetime.timedeltas. Deleted s3 objects have no tags, and thus no
    place for backup to store the time of event. So restore uses
    LastModified, which requires a second to pass (no microseconds
    from original source).
    """
    deleted_params = {}
    for i, name in enumerate(names):
        what_type = "SecureString" if i % 5 == 0 else "String"
        message = prep_message(name, "Delete", what_type)
        action = ssmbak.process_message(message)
        deleted_param = prep(action)
        updated_action = update_time(action)
        logger.debug("updated_action: %s", updated_action)
        ssmbak.backup(updated_action)
        deleted_params[name] = deleted_param
        logger.info("%s deleted", name)
    # deleteds have no tags, so LastModified, thus sleep
    logger.info("sleeping at %s", datetime.now(tz=timezone.utc))
    n = 2
    time.sleep(n)
    deltime = datetime.now(tz=timezone.utc) - timedelta(0, n / 2)
    ## update one more
    for i, name in enumerate(names):
        what_type = "SecureString" if i % 5 == 0 else "String"
        message = prep_message(name, "Update", what_type)
        action = ssmbak.process_message(message)
        prep(action)
        post_delete_action = update_time(action)
        ssmbak.backup(post_delete_action)
    # pylint: disable=fixme
    # TODO: test to make sure deleteds don't appear if not there_now?
    logger.info("done delete/update at %s", datetime.now(tz=timezone.utc))
    return deltime, deleted_params


def create_and_check(names):
    """Seeds a test with a bunch of params for names.

    Quickly checks them before returning.
    """
    initial_params = {}
    for i, name in enumerate(names):
        # throw in some descriptions and types
        description = (i % 3 == 0) or False
        what_type = "SecureString" if i % 5 == 0 else "String"
        message = prep_message(name, "Create", what_type, description=description)
        action = ssmbak.process_message(message)
        initial_param = prep(action)
        logger.debug("initial_param: %s", pretty(initial_param))
        initial_params[name] = initial_param
        logger.debug("action: %s", pretty(action))
        ssmbak.backup(action)
        ssm_param = pytest.ssm.get_parameter(Name=name, WithDecryption=True)[
            "Parameter"
        ]
        logger.debug("ssm_param: %s", pretty(ssm_param))
        ssm_param_desc = pytest.ssm.describe_parameters(
            ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}]
        )["Parameters"][0]
        logger.debug("ssm_param_desc: %s", pretty(ssm_param_desc))
        assert ssm_param["Value"] == initial_param["Value"]
        assert ssm_param["Type"] == initial_param["Type"]
        if "Description" in ssm_param_desc:
            assert ssm_param_desc["Description"] == initial_param["Description"]
        pytest.s3.get_object(Bucket=pytest.bucketname, Key=action["name"])
    return initial_params


def update_and_check(names):
    """Updates previously created names.

    Quickly checks them before returning. Also tweaks some
    descriptions and types to make sure nothing slips through.
    """
    updated_params = {}
    for i, name in enumerate(names):
        # throw in some descriptions and types
        description = (i % 5 == 0) or False
        what_type = "SecureString" if i % 5 == 0 else "String"
        message = prep_message(name, "Update", what_type, description=description)
        action = ssmbak.process_message(message)
        updated_param = prep(action)
        updated_params[name] = updated_param
        updated_action = update_time(action)
        logger.debug(updated_action)
        ssmbak.backup(update_type(update_description(updated_action, "fugly")))
        ssm_param = pytest.ssm.get_parameter(Name=name, WithDecryption=True)[
            "Parameter"
        ]
        logger.debug("ssm_param: %s", pretty(ssm_param))
        ssm_param_desc = pytest.ssm.describe_parameters(
            ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}]
        )["Parameters"][0]
        logger.debug("ssm_param_desc: %s", pretty(ssm_param_desc))
        assert ssm_param["Value"] == updated_param["Value"]
        assert ssm_param["Type"] == updated_param["Type"]
        if "Description" in updated_param:
            assert ssm_param_desc["Description"] == updated_param["Description"]
        else:
            with pytest.raises(KeyError):
                assert ssm_param_desc["Description"] == updated_param["Description"]
        assert ssm_param["Value"] == updated_param["Value"]
    return updated_params


def compare_previews_with_params(previews, params):
    """DRY for preview/restore comparison with correct ones."""
    for preview in previews:
        assert preview["Name"] == params[preview["Name"]]["Name"]
        assert preview["Value"] == params[preview["Name"]]["Value"]
        if "Description" in preview:
            assert preview["Description"] == params[preview["Name"]]["Description"]
        assert preview["Type"] == params[preview["Name"]]["Type"]


def check_classvar_counts(calls):
    """Check efforts to minimize calls to AWS APIs."""
    actual_calls = Resource.get_calls()
    logger.info(actual_calls)
    assert actual_calls["tags"] == calls["tags"]
    assert actual_calls["versions"] == calls["versions"]
    assert actual_calls["version_objects"] == calls["version_objects"]


def delete_some(n, names):
    """Delete n random elements from a list."""
    random_indices = random.sample(range(0, len(names) - n), n)
    return n, [names[i] for i in random_indices]
