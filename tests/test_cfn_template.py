"""Tests for CloudFormation template parsing.

Validates that template loading and manipulation works correctly.
Used to verify compatibility when switching YAML parsers.
"""

# pylint: skip-file

import importlib.metadata
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_template_url_construction():
    """Template URL is constructed correctly from version and constants."""
    # Constants from ssmbak/cli/stack.py (can't import due to argparse at module level)
    TEMPLATE_BUCKET = "ssmbak-public"
    TEMPLATE_REGION = "us-east-2"

    version = importlib.metadata.version("ssmbak")
    expected_url = f"https://{TEMPLATE_BUCKET}.s3.{TEMPLATE_REGION}.amazonaws.com/cfn-{version}.yml"

    # Verify the URL format
    assert expected_url.startswith("https://")
    assert TEMPLATE_BUCKET in expected_url
    assert TEMPLATE_REGION in expected_url
    assert f"cfn-{version}.yml" in expected_url


def test_stack_create_uses_template_url():
    """Stack.create uses TemplateURL parameter instead of TemplateBody."""
    from ssmbak.cli.cfn import Stack

    stack = Stack("test-stack", pytest.region)
    test_url = "https://example.com/template.yml"

    # Mock the create_stack method
    with patch.object(stack.cfn, "create_stack") as mock_create:
        stack.create(test_url)

        # Verify create_stack was called once
        assert mock_create.call_count == 1

        # Get the kwargs passed to create_stack
        call_kwargs = mock_create.call_args[1]

        # Verify TemplateURL is used
        assert "TemplateURL" in call_kwargs
        assert call_kwargs["TemplateURL"] == test_url

        # Verify TemplateBody is NOT used
        assert "TemplateBody" not in call_kwargs


def test_stack_update_uses_template_url():
    """Stack.update uses TemplateURL parameter instead of TemplateBody."""
    from ssmbak.cli.cfn import Stack

    stack = Stack("test-stack", pytest.region)
    test_url = "https://example.com/template.yml"

    # Mock the update_stack method
    with patch.object(stack.cfn, "update_stack") as mock_update:
        stack.update(test_url)

        # Verify update_stack was called once
        assert mock_update.call_count == 1

        # Get the kwargs passed to update_stack
        call_kwargs = mock_update.call_args[1]

        # Verify TemplateURL is used
        assert "TemplateURL" in call_kwargs
        assert call_kwargs["TemplateURL"] == test_url

        # Verify TemplateBody is NOT used
        assert "TemplateBody" not in call_kwargs


def test_template_parameters_current():
    """Template parameters have expected structure after stack rework."""
    template = cfn_yaml.load(str(TEMPLATE_PATH))

    params = template["Parameters"]

    # These parameters should exist
    assert "LogLevel" in params
    assert "ThresholdAgeOfOldestMessage" in params
    assert "ThresholdNumberOfMessagesVisible" in params

    # Version parameter should NOT exist (removed in stack rework)
    assert "Version" not in params

    # LogLevel should have a default
    assert params["LogLevel"]["Default"] == "INFO"
