"""shared functions"""

import logging
import os
from pathlib import Path

import boto3
import yaml

logger = logging.getLogger(__name__)


def slurp(filename):
    """Suck a file into a str."""
    with open(filename, encoding="utf-8") as x:
        f = x.read()
    return f


def _any_constructor(loader, tag_suffix, node):  # pylint: disable=unused-argument
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


def sort_bucket(bucketname, region):
    """Figures out where the backup bucket is, first by arg then by SSM Param.

    The stack created by ssmbak-stack create <STACKNAME> will write that param.
    """
    if bucketname:
        res = bucketname
        logger.info("%s set by arg", res)
    else:
        template_dir = Path(__file__).parent.parent
        template_file = f"{template_dir}/data/cfn.yml"
        yaml.add_multi_constructor("", _any_constructor, Loader=yaml.SafeLoader)
        template = yaml.safe_load(slurp(template_file))
        key = template["Resources"]["BucketParam"]["Properties"]["Name"]
        ssm = boto3.client(
            "ssm", endpoint_url=os.getenv("AWS_ENDPOINT"), region_name=region
        )
        bucket_param = ssm.get_parameter(Name=key)
        res = bucket_param["Parameter"]["Value"]
        logger.info("%s set by SSM param %s", res, bucket_param["Parameter"]["Name"])
    return res


def sort_region(region):
    """Set region if provided, see if boto can figure it out otherwise."""
    if region:
        logger.info("%s set by arg", region)
        return region
    session = boto3.session.Session()
    if session.region_name:
        logger.info("%s set by session", session.region_name)
        return session.region_name
    return None
