"""LocalStack safety enforcement for tests.

Prevents any boto3/botocore client or resource creation from connecting to
real AWS. Applied at import time from tests/conftest.py.
"""

import os

import boto3
import botocore.session

ALLOWED_ENDPOINTS = frozenset({
    "http://localhost:4566",
    "http://localstack:4566",
})

_original_boto3_client = boto3.client
_original_boto3_resource = boto3.resource
_original_boto3_session_client = boto3.Session.client
_original_boto3_session_resource = boto3.Session.resource
_original_botocore_create_client = botocore.session.Session.create_client


def _check_endpoint(kwargs, label):
    endpoint = kwargs.get("endpoint_url") or os.getenv("AWS_ENDPOINT")
    if not endpoint or endpoint not in ALLOWED_ENDPOINTS:
        raise RuntimeError(
            f"Blocked {label} creation without LocalStack endpoint!\n"
            f"  endpoint_url={kwargs.get('endpoint_url')}\n"
            f"  AWS_ENDPOINT={os.getenv('AWS_ENDPOINT')}"
        )
    kwargs["endpoint_url"] = endpoint


def _safe_boto3_client(service_name, **kwargs):
    _check_endpoint(kwargs, f"boto3.client {service_name}")
    return _original_boto3_client(service_name, **kwargs)


def _safe_boto3_resource(service_name, **kwargs):
    _check_endpoint(kwargs, f"boto3.resource {service_name}")
    return _original_boto3_resource(service_name, **kwargs)


def _safe_boto3_session_client(self, service_name, *args, **kwargs):
    _check_endpoint(kwargs, f"boto3.Session.client {service_name}")
    return _original_boto3_session_client(self, service_name, *args, **kwargs)


def _safe_boto3_session_resource(self, service_name, *args, **kwargs):
    _check_endpoint(kwargs, f"boto3.Session.resource {service_name}")
    return _original_boto3_session_resource(self, service_name, *args, **kwargs)


def _safe_botocore_create_client(self, *args, **kwargs):
    _check_endpoint(kwargs, "botocore.Session.create_client")
    return _original_botocore_create_client(self, *args, **kwargs)


def apply_safety_patch():
    """Patch all AWS client/resource creation paths to enforce LocalStack endpoint."""
    boto3.client = _safe_boto3_client
    boto3.resource = _safe_boto3_resource
    boto3.Session.client = _safe_boto3_session_client
    boto3.Session.resource = _safe_boto3_session_resource
    botocore.session.Session.create_client = _safe_botocore_create_client
