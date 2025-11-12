"""Module to handle Cloudformation stack options for the bucket/lambda."""

import logging
import os
import re
import sys
import time
from pathlib import Path

import boto3
import yaml

logger = logging.getLogger(__name__)


# CloudFormation intrinsic function support for YAML load/dump
def _cfn_constructor(loader, tag_suffix, node):
    """Handle CloudFormation intrinsic functions like !Ref, !GetAtt, !Sub."""
    if isinstance(node, yaml.ScalarNode):
        return {tag_suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {tag_suffix: loader.construct_sequence(node)}
    if isinstance(node, yaml.MappingNode):
        return {tag_suffix: loader.construct_mapping(node)}
    return {tag_suffix: node.value}


yaml.SafeLoader.add_multi_constructor("!", _cfn_constructor)


def _cfn_representer(dumper, data):
    """Represent CloudFormation intrinsic functions with ! tag syntax.

    Handles CloudFormation intrinsic functions. Our constructor creates dicts like
    {"GetAtt": "Q.Arn"} from !GetAtt tags. We convert them back to ! syntax.

    Uses explicit list of CloudFormation intrinsic function names to avoid false
    positives on regular properties like "ZipFile" or "Code".
    """
    if isinstance(data, dict) and len(data) == 1:
        key = next(iter(data))

        # CloudFormation intrinsic function names (what appears after ! in YAML)
        # This list is stable - AWS rarely adds new intrinsic functions
        cfn_functions = {
            "Ref",
            "Condition",
            "GetAtt",
            "Sub",
            "Join",
            "Select",
            "Split",
            "FindInMap",
            "GetAZs",
            "ImportValue",
            "Base64",
            "Cidr",
            "If",
            "And",
            "Or",
            "Not",
            "Equals",
        }

        if key in cfn_functions:
            value = data[key]
            if isinstance(value, str):
                return dumper.represent_scalar(f"!{key}", value)
            if isinstance(value, list):
                return dumper.represent_sequence(f"!{key}", value)
            if isinstance(value, dict):
                return dumper.represent_mapping(f"!{key}", value)
    return dumper.represent_dict(data)


# Custom dumper that handles CloudFormation tags
class CfnDumper(yaml.SafeDumper):
    """YAML dumper with CloudFormation intrinsic function support."""


CfnDumper.add_representer(dict, _cfn_representer)


class Stack:
    """For manipulating cloudformation stacks"""

    def __init__(self, name, region):
        self.name = name
        self.region = region
        self.cfn = boto3.client(
            "cloudformation",
            endpoint_url=os.getenv("AWS_ENDPOINT"),
            region_name=self.region,
        )

    def __repr__(self):
        return f"{self.__class__.__name__} {self.name} ({self.region})"

    @property
    def bucketname(self):
        """Returns just the bucketname created by the stack."""
        resources = self.resources()
        bucketname = [
            x["physical"] for x in resources if x["type"] == "AWS::S3::Bucket"
        ][0]
        return bucketname

    @property
    def lambdaname(self):
        """Returns just the lambda created by the stack.

        Good for logs in the awscli, e.g.
        aws logs tail /aws/lambda/dev-ssmbak-resource-Function-SEmkoVs3DSgs
        """
        resources = self.resources()
        lambdaname = [
            x["physical"] for x in resources if x["type"] == "AWS::Lambda::Function"
        ][0]
        return lambdaname

    def params(self):
        """Returns a list of the stack's Parameters."""
        response = self.cfn.describe_stacks(StackName=self.name)
        parameters = response["Stacks"][0]["Parameters"]
        for parameter in parameters:
            parameter["region"] = self.region
        return parameters

    def resources(self, full=False):
        """Returns a list of the stack's resources."""
        # can't paginate
        response = self.cfn.describe_stack_resources(StackName=self.name)
        resources = response["StackResources"]
        if full:
            result = resources
        else:
            result = []
            for resource in resources:
                res = {}
                res["time"] = resource["Timestamp"].strftime("%b %d %Y %H:%M:%S")
                res["status"] = resource["ResourceStatus"]
                res["logical"] = resource["LogicalResourceId"]
                res["physical"] = resource["PhysicalResourceId"]
                res["type"] = resource["ResourceType"]
                result.append(res)
        return result

    def _kwargify_params(self, params, template_file):
        parameters = [
            {"ParameterKey": name, "ParameterValue": value}
            for name, value in params.items()
        ]

        with open(template_file, encoding="utf-8") as f:
            template = yaml.safe_load(f)
        template["Resources"]["Function"]["Properties"]["Code"]["ZipFile"] = Path(
            f"{Path(__file__).parent.parent}/backup/ssmbak.py"
        ).read_text(encoding="utf-8")
        template_body = yaml.dump(template, Dumper=CfnDumper, default_flow_style=False)
        kwargs = {
            "StackName": self.name,
            "Parameters": parameters,
            "Capabilities": ["CAPABILITY_NAMED_IAM"],
            "TemplateBody": template_body,
        }
        return kwargs

    def create(self, template_file, params):
        """Creates the stack."""
        logger.debug("params = %s", params)
        kwargs = self._kwargify_params(params, template_file)
        logger.debug(kwargs)
        self.cfn.create_stack(**kwargs)

    def update(self, template_file, params):
        """Creates the stack."""
        logger.debug("params = %s", params)
        kwargs = self._kwargify_params(params, template_file)
        logger.debug(kwargs)
        self.cfn.update_stack(**kwargs)

    def events(self, last=None):
        """Returns a list of all stack events."""
        consolidated_events = []
        paginator = self.cfn.get_paginator("describe_stack_events")
        paginated = paginator.paginate(StackName=self.name)
        # wouldbenice: process as we go until a stack _COMPLETE
        events = paginated.build_full_result()["StackEvents"]
        if last:
            events = [x for x in events if x["Timestamp"] > last]
        for event in events:
            deets = {
                "time": event["Timestamp"],
                "logicalId": event["LogicalResourceId"],
                "type": event["ResourceType"],
                "status": event["ResourceStatus"],
            }
            try:
                deets["reason"] = event["ResourceStatusReason"]
            except KeyError:
                deets["reason"] = ""
            consolidated_events.append(deets)
        return consolidated_events

    def watch(
        self,
        looking_for=r"(_COMPLETE|_FAILED)$",
        come_back=False,
        interval=10,
    ):
        """Will wait for stack operations to end, printing all events along the way."""
        stack_complete = None
        last = None
        while not stack_complete:
            logger.debug("last: %s", last)
            events = self.events(last=last)
            try:
                latest = events[0]
            except IndexError:
                time.sleep(interval)
                continue
            except TypeError:
                break
            if not last:
                events_to_show = [events[0]]
            else:
                events_to_show = events
            try:
                events.reverse()
            except TypeError:
                events = []
            for event in events_to_show:
                line = (
                    f"{event['time'].strftime('%m/%d/%y %H:%M:%S')}   "
                    f"{event['status']}  "
                    f"{event['logicalId']}  "
                    f"{event['type']}  "
                    f"{event['reason']}"
                )
                print(line)
                if event["type"] == "AWS::CloudFormation::Stack" and re.search(
                    looking_for, event["status"]
                ):
                    # wouldbenice: printemall first, then puke on failure
                    if re.search(r"(ROLLBACK_COMPLETE|FAILED)$", event["status"]):
                        if come_back:
                            return True
                        sys.exit(1)  # don't know
                    return event["status"]  # ugly
            last = latest["time"]
            time.sleep(interval)
        try:
            return latest
        except UnboundLocalError:
            return None

    def status(self):
        """Current operational status of the stack."""
        result = None
        for event in self.events():
            if result:
                break
            if event["type"] == "AWS::CloudFormation::Stack":
                result = event["status"]
                break
        return result
