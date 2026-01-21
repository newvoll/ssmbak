"""Unit tests for use_tags parameter in _get_versions().

These tests verify that use_tags=False correctly skips tag fetching
and uses LastModified directly as event time.
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ssmbak.restore.aws import Resource

logger = logging.getLogger(__name__)


class TestUseTags:
    """Tests for the use_tags parameter in _get_versions()."""

    def setup_method(self):
        """Reset call cache before each test."""
        Resource.clear_call_cache()

    def test_use_tags_true_fetches_tagset(self):
        """When use_tags=True (default), _get_tagset is called for each version."""
        resource = Resource("us-east-1", "test-bucket")
        checktime = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # Mock S3 responses
        mock_version = {
            "Key": "test-key",
            "VersionId": "v1",
            "LastModified": datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
            "ETag": '"abc123"',
            "Size": 100,
            "StorageClass": "STANDARD",
            "IsLatest": True,
            "Owner": {"DisplayName": "test", "ID": "123"},
        }

        with patch.object(resource, "_get_object_versions") as mock_paginator:
            # Setup mock paginator
            mock_page = MagicMock()
            mock_page.__iter__ = lambda self: iter([{"Versions": [mock_version]}])
            mock_paginator.return_value = mock_page

            with patch.object(resource, "_get_tagset") as mock_get_tagset:
                mock_get_tagset.return_value = {
                    "ssmbakTime": "1704880800",  # 2024-01-10 10:00:00 UTC
                    "ssmbakType": "String",
                }

                result = resource._get_versions("test-key", checktime, use_tags=True)

                # Verify _get_tagset was called
                assert mock_get_tagset.call_count >= 1, "_get_tagset should be called when use_tags=True"

    def test_use_tags_false_skips_tagset(self):
        """When use_tags=False, _get_tagset is NOT called."""
        resource = Resource("us-east-1", "test-bucket")
        checktime = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # Mock S3 responses
        mock_version = {
            "Key": "test-key",
            "VersionId": "v1",
            "LastModified": datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
            "ETag": '"abc123"',
            "Size": 100,
            "StorageClass": "STANDARD",
            "IsLatest": True,
            "Owner": {"DisplayName": "test", "ID": "123"},
        }

        with patch.object(resource, "_get_object_versions") as mock_paginator:
            # Setup mock paginator
            mock_page = MagicMock()
            mock_page.__iter__ = lambda self: iter([{"Versions": [mock_version]}])
            mock_paginator.return_value = mock_page

            with patch.object(resource, "_get_tagset") as mock_get_tagset:
                result = resource._get_versions("test-key", checktime, use_tags=False)

                # Verify _get_tagset was NOT called
                assert mock_get_tagset.call_count == 0, "_get_tagset should NOT be called when use_tags=False"

    def test_use_tags_false_uses_lastmodified_as_time(self):
        """When use_tags=False, LastModified is used as the version time."""
        resource = Resource("us-east-1", "test-bucket")
        version_time = datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
        checktime = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_version = {
            "Key": "test-key",
            "VersionId": "v1",
            "LastModified": version_time,
            "ETag": '"abc123"',
            "Size": 100,
            "StorageClass": "STANDARD",
            "IsLatest": True,
            "Owner": {"DisplayName": "test", "ID": "123"},
        }

        with patch.object(resource, "_get_object_versions") as mock_paginator:
            mock_page = MagicMock()
            mock_page.__iter__ = lambda self: iter([{"Versions": [mock_version]}])
            mock_paginator.return_value = mock_page

            result = resource._get_versions("test-key", checktime, use_tags=False)

            # Verify a version was returned
            assert "test-key" in result
            # Verify tagset is empty (not fetched)
            assert result["test-key"]["tagset"] == {}
            # Verify the version has the correct LastModified
            assert result["test-key"]["LastModified"] == version_time

    def test_use_tags_false_sets_empty_tagset(self):
        """When use_tags=False, tagset is set to empty dict."""
        resource = Resource("us-east-1", "test-bucket")
        checktime = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        mock_version = {
            "Key": "test-key",
            "VersionId": "v1",
            "LastModified": datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
            "ETag": '"abc123"',
            "Size": 100,
            "StorageClass": "STANDARD",
            "IsLatest": True,
            "Owner": {"DisplayName": "test", "ID": "123"},
        }

        with patch.object(resource, "_get_object_versions") as mock_paginator:
            mock_page = MagicMock()
            mock_page.__iter__ = lambda self: iter([{"Versions": [mock_version]}])
            mock_paginator.return_value = mock_page

            result = resource._get_versions("test-key", checktime, use_tags=False)

            assert "test-key" in result
            assert result["test-key"]["tagset"] == {}

    def test_use_tags_false_filters_by_lastmodified(self):
        """When use_tags=False, versions are filtered using LastModified, not tags."""
        resource = Resource("us-east-1", "test-bucket")
        checktime = datetime(2024, 1, 12, 12, 0, 0, tzinfo=timezone.utc)

        # Version before checktime - should be included
        old_version = {
            "Key": "test-key",
            "VersionId": "v1",
            "LastModified": datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
            "ETag": '"abc123"',
            "Size": 100,
            "StorageClass": "STANDARD",
            "IsLatest": False,
            "Owner": {"DisplayName": "test", "ID": "123"},
        }

        # Version after checktime - should be excluded
        new_version = {
            "Key": "test-key",
            "VersionId": "v2",
            "LastModified": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            "ETag": '"def456"',
            "Size": 100,
            "StorageClass": "STANDARD",
            "IsLatest": True,
            "Owner": {"DisplayName": "test", "ID": "123"},
        }

        with patch.object(resource, "_get_object_versions") as mock_paginator:
            mock_page = MagicMock()
            # Note: S3 returns newest first
            mock_page.__iter__ = lambda self: iter([{"Versions": [new_version, old_version]}])
            mock_paginator.return_value = mock_page

            result = resource._get_versions("test-key", checktime, use_tags=False)

            # Should only include the old version (before checktime)
            assert "test-key" in result
            assert result["test-key"]["VersionId"] == "v1"
            assert result["test-key"]["LastModified"] == datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc)

    def test_use_tags_false_selects_latest_before_checktime(self):
        """When use_tags=False with multiple versions before checktime, select most recent."""
        resource = Resource("us-east-1", "test-bucket")
        checktime = datetime(2024, 1, 20, 12, 0, 0, tzinfo=timezone.utc)

        versions = [
            {
                "Key": "test-key",
                "VersionId": "v3",
                "LastModified": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "ETag": '"ghi789"',
                "Size": 100,
                "StorageClass": "STANDARD",
                "IsLatest": True,
                "Owner": {"DisplayName": "test", "ID": "123"},
            },
            {
                "Key": "test-key",
                "VersionId": "v2",
                "LastModified": datetime(2024, 1, 10, 10, 0, 0, tzinfo=timezone.utc),
                "ETag": '"def456"',
                "Size": 100,
                "StorageClass": "STANDARD",
                "IsLatest": False,
                "Owner": {"DisplayName": "test", "ID": "123"},
            },
            {
                "Key": "test-key",
                "VersionId": "v1",
                "LastModified": datetime(2024, 1, 5, 10, 0, 0, tzinfo=timezone.utc),
                "ETag": '"abc123"',
                "Size": 100,
                "StorageClass": "STANDARD",
                "IsLatest": False,
                "Owner": {"DisplayName": "test", "ID": "123"},
            },
        ]

        with patch.object(resource, "_get_object_versions") as mock_paginator:
            mock_page = MagicMock()
            mock_page.__iter__ = lambda self: iter([{"Versions": versions}])
            mock_paginator.return_value = mock_page

            result = resource._get_versions("test-key", checktime, use_tags=False)

            # Should select v3 (most recent before checktime)
            assert "test-key" in result
            assert result["test-key"]["VersionId"] == "v3"
