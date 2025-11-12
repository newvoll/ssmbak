"""Tests for CloudFormation template parsing.

Validates that template loading and manipulation works correctly.
Used to verify compatibility when switching YAML parsers.
"""

# pylint: skip-file

import logging
from pathlib import Path

import pytest
import yaml
from cfnlint.decode import cfn_yaml

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent.parent / "ssmbak" / "data" / "cfn.yml"


def test_template_file_exists():
    """CloudFormation template file exists."""
    assert TEMPLATE_PATH.exists(), f"Template not found at {TEMPLATE_PATH}"


def test_template_loads():
    """Template loads without errors and has expected structure."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    assert "AWSTemplateFormatVersion" in template
    assert "Resources" in template
    assert "Parameters" in template
    assert template["AWSTemplateFormatVersion"] == "2010-09-09"


def test_intrinsic_functions_preserved():
    """CloudFormation intrinsic functions (!Ref, etc.) are preserved."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    # Check !Ref AWS::StackName in StackParam
    stack_param = template["Resources"]["StackParam"]
    assert stack_param["Properties"]["Value"] == {"Ref": "AWS::StackName"}

    # Check !Ref Bucket in BucketParam
    bucket_param = template["Resources"]["BucketParam"]
    assert bucket_param["Properties"]["Value"] == {"Ref": "Bucket"}


def test_template_resources_present():
    """All expected resources are present in template."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    expected_resources = {
        "StackParam",
        "BucketParam",
        "Bucket",
        "Function",
        "FunctionRole",
        "Q",
        "EventRule",
    }

    actual_resources = set(template["Resources"].keys())
    assert expected_resources.issubset(
        actual_resources
    ), f"Missing resources: {expected_resources - actual_resources}"


def test_lambda_code_injection():
    """Can inject Lambda code into Function resource."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    # Simulate what _kwargify_params does
    test_code = "def lambda_handler(event, context):\n    return 'test'"
    template["Resources"]["Function"]["Properties"]["Code"]["ZipFile"] = test_code

    # Verify code was injected
    assert (
        template["Resources"]["Function"]["Properties"]["Code"]["ZipFile"] == test_code
    )


def test_yaml_dump_works():
    """Can dump template to YAML (used by cfn.py)."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    # Dump to YAML string (what cfn.py does)
    yaml_str = yaml.dump(template)

    # Verify it's a string and contains expected content
    assert isinstance(yaml_str, str)
    assert len(yaml_str) > 1000  # Template should be substantial
    assert "Resources" in yaml_str or "resources" in yaml_str


def test_template_parameters():
    """Template parameters have expected structure."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    params = template["Parameters"]
    assert "Version" in params
    assert "LogLevel" in params

    # LogLevel should have a default
    assert params["LogLevel"]["Default"] == "INFO"


def test_kwargify_params_template_size():
    """Template body from _kwargify_params should be reasonable size with Lambda code injected.

    This test verifies that the CloudFormation template preparation doesn't bloat
    the template with metadata or serialization artifacts.
    """
    from ssmbak.cli.cfn import Stack

    # Create a Stack instance (uses localstack via fixtures)
    stack = Stack("test-stack", pytest.region)

    # Call _kwargify_params with test parameters
    template_file = str(TEMPLATE_PATH)
    params = {"Version": "0.1.0"}
    kwargs = stack._kwargify_params(params, template_file)

    # Verify kwargs structure
    assert "TemplateBody" in kwargs
    template_body = kwargs["TemplateBody"]

    # Template body should be a string
    assert isinstance(template_body, str)

    # Parse it back to verify it's valid YAML
    parsed = yaml.safe_load(template_body)
    assert isinstance(parsed, dict)
    assert "Resources" in parsed
    assert "Function" in parsed["Resources"]

    # Lambda code should be injected
    lambda_code = parsed["Resources"]["Function"]["Properties"]["Code"]["ZipFile"]
    assert lambda_code is not None
    assert len(lambda_code) > 100  # Should contain actual Lambda function code
    assert "def handler" in lambda_code

    # Template body should be reasonable size (< 100KB)
    # Original template is ~5KB, Lambda code is ~10KB, total should be < 100KB
    template_size = len(template_body)
    assert template_size < 100000, (
        f"Template body is {template_size} bytes ({template_size // 1024}KB), "
        f"expected < 100KB. This suggests metadata is being serialized."
    )

    # Should not contain Python object serialization
    assert (
        "!!python/object" not in template_body
    ), "Template contains Python object serialization"
    assert (
        "cfnlint.decode.node" not in template_body
    ), "Template contains cfn-lint metadata"


def test_kwargify_params_cfn_tags_preserved():
    """Template body preserves CloudFormation intrinsic function tags."""
    from ssmbak.cli.cfn import Stack

    # Get processed template
    stack = Stack("test-stack", pytest.region)
    kwargs = stack._kwargify_params({"Version": "0.1.0"}, str(TEMPLATE_PATH))
    template_body = kwargs["TemplateBody"]

    # Verify CloudFormation tags are preserved with ! syntax
    assert "!Ref" in template_body, "!Ref tags not preserved"
    assert "!GetAtt" in template_body, "!GetAtt tags not preserved"
    assert "!Sub" in template_body, "!Sub tags not preserved"

    # Verify no expanded dict format
    assert (
        "Ref:" not in template_body or "!Ref" in template_body
    ), "Tags expanded to dict format"

    # Parse and verify structure
    parsed = yaml.safe_load(template_body)
    assert "Resources" in parsed
    assert "Function" in parsed["Resources"]

    # Verify Lambda code was injected
    lambda_code = parsed["Resources"]["Function"]["Properties"]["Code"]["ZipFile"]
    assert len(lambda_code) > 100
    assert "def handler" in lambda_code


def test_kwargify_params_cfn_validation():
    """Template body is valid CloudFormation template that cfn-lint can parse."""
    import tempfile

    from cfnlint import decode

    from ssmbak.cli.cfn import Stack

    # Get processed template
    stack = Stack("test-stack", pytest.region)
    kwargs = stack._kwargify_params({"Version": "0.1.0"}, str(TEMPLATE_PATH))
    template_body = kwargs["TemplateBody"]

    # Write to temp file for cfn-lint validation
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        f.write(template_body)
        temp_path = f.name

    try:
        # Load template with cfn-lint (returns tuple of template and matches)
        # This validates that the template is valid CloudFormation YAML
        template, matches = decode.decode(temp_path)

        # Basic validation - template should load without errors
        assert template is not None, "Template failed to load with cfn-lint"
        assert "Resources" in template, "Template missing Resources section"
        assert "Function" in template["Resources"], "Template missing Function resource"

        # Verify Lambda code was injected and preserved
        function = template["Resources"]["Function"]
        assert "Properties" in function
        assert "Code" in function["Properties"]
        assert "ZipFile" in function["Properties"]["Code"]

        zipfile = function["Properties"]["Code"]["ZipFile"]
        assert len(zipfile) > 100, "Lambda code not properly injected"
        assert "def handler" in zipfile, "Lambda handler function missing"

        # Check for any parse errors from cfn-lint
        parse_errors = [m for m in matches if "parse" in str(m).lower()]
        assert len(parse_errors) == 0, f"CloudFormation parse errors: {parse_errors}"

    finally:
        # Cleanup
        import os

        os.unlink(temp_path)


def test_kwargify_params_aws_validation():
    """Template body is valid according to AWS CloudFormation API."""
    import os

    import boto3

    from ssmbak.cli.cfn import Stack

    # Get processed template
    stack = Stack("test-stack", pytest.region)
    kwargs = stack._kwargify_params({"Version": "0.1.0"}, str(TEMPLATE_PATH))
    template_body = kwargs["TemplateBody"]

    # Validate against AWS CloudFormation API (localstack)
    cfn = boto3.client(
        "cloudformation",
        region_name=pytest.region,
        endpoint_url=os.getenv("AWS_ENDPOINT"),
    )
    response = cfn.validate_template(TemplateBody=template_body)

    # Verify response indicates valid template
    assert "Parameters" in response, "AWS validation response missing Parameters"
    assert "Description" in response, "AWS validation response missing Description"
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200, "Validation failed"

    # Verify expected parameters are present
    param_keys = {p["ParameterKey"] for p in response["Parameters"]}
    assert "Version" in param_keys, "Version parameter not found"
    assert "LogLevel" in param_keys, "LogLevel parameter not found"
    assert "ThresholdAgeOfOldestMessage" in param_keys
    assert "ThresholdNumberOfMessagesVisible" in param_keys

    # Verify parameter defaults are preserved
    log_level_param = next(
        p for p in response["Parameters"] if p["ParameterKey"] == "LogLevel"
    )
    assert log_level_param["DefaultValue"] == "INFO", "LogLevel default not preserved"
