"""Generic point-in-time queries against a versioned S3 bucket.

Mirrors :class:`ssmbak.restore.actions.ParamPath` but for arbitrary S3 keys
not managed by ssmbak's Lambda. Uses S3 ``LastModified`` directly as event
time (no ``ssmbakTime`` tag dance), so it works on any versioned bucket.

Single-key only. Recursion/path semantics belong elsewhere.

Typical usage::

    from datetime import datetime, timezone
    from ssmbak.restore.s3 import S3Path

    s3path = S3Path("my/key", datetime(2024, 6, 9, 12, tzinfo=timezone.utc),
                    "us-west-2", "my-bucket")

    s3path.preview()   # version that would be restored, or None
    s3path.body()      # in-memory content (suitable for small objects)
    s3path.restore()   # copy that version to current (or delete for delete markers)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ssmbak.restore.aws import Resource

if TYPE_CHECKING:
    from datetime import datetime
    from typing import IO

    from ssmbak.typing import Version

logger = logging.getLogger(__name__)


class S3Path(Resource):
    """A single S3 key to query or restore at a point in time.

    Attributes:
      key: The S3 object key.
      checktime: The point in time for which to retrieve the latest version.
      version: Cache populated by ``preview()``. ``None`` means "not looked up
        yet" before the first call and "no version at or before checktime"
        after it; check via ``preview()``'s return value, not this attribute.
    """

    def __init__(self, key: str, checktime: datetime, region: str, bucketname: str):
        self.key = key
        self.checktime = checktime
        self.version: Version | None = None
        super().__init__(region, bucketname)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}({self.key}, "
            f"{self.checktime.strftime('%Y-%m-%dT%H:%M:%SZ')}, "
            f"{self.region}, {self.bucketname})"
        )

    def preview(self) -> Version | None:
        """Return the version that would be restored at ``checktime``.

        Returns the S3 version dict (with ``Deleted: True`` for delete markers)
        or ``None`` if no version exists at or before ``checktime``. Caches the
        result in ``self.version`` for subsequent ``body()`` / ``download_to()``
        / ``restore()`` calls.
        """
        versions, _ = self._get_versions(self.key, self.checktime, recurse=False, use_tags=False)
        version = versions.get(self.key)
        if version is None:
            logger.warning("No version of %s at or before %s", self.key, self.checktime)
            self.version = None
            return None
        self.version = version
        return version

    def body(self) -> str:
        """Fetch the version's content in memory as a string.

        Returns ``""`` for delete markers and when no version exists. Suitable
        for small/medium content; for large objects use ``download_to``.
        """
        if self.version is None:
            self.preview()
        if self.version is None or self.version.get("Deleted"):
            return ""
        return self._get_version_body(self.key, self.version["VersionId"])

    def download_to(self, fileobj: IO[bytes]) -> None:
        """Stream the version's content into a writable binary file-like.

        Raises ``ValueError`` if no version exists at ``checktime`` or if the
        relevant version is a delete marker.
        """
        if self.version is None:
            self.preview()
        if self.version is None:
            raise ValueError(f"No version of {self.key} at or before {self.checktime}")
        if self.version.get("Deleted"):
            raise ValueError(f"{self.key} was deleted at {self.version['LastModified']}")
        self.s3.download_fileobj(
            Bucket=self.bucketname,
            Key=self.key,
            Fileobj=fileobj,
            ExtraArgs={"VersionId": self.version["VersionId"]},
        )

    def restore(self) -> Version | None:
        """Copy the version at ``checktime`` to current.

        For a real version: server-side ``copy_object``. For a delete marker:
        ``delete_object`` (creates a new delete marker, restoring "deleted"
        state). Returns the same dict as ``preview()`` or ``None`` if nothing
        exists at ``checktime``.
        """
        if self.version is None:
            self.preview()
        if self.version is None:
            return None
        if self.version.get("Deleted"):
            self.s3.delete_object(Bucket=self.bucketname, Key=self.key)
        else:
            self._copy_version_to_current(self.version["VersionId"])
        return self.version

    def _copy_version_to_current(self, version_id: str) -> None:
        # S3 rejects a same-bucket-same-key copy unless MetadataDirective is
        # REPLACE, so we head the source version and pass its metadata through
        # explicitly to preserve ContentType, user metadata, etc.
        head = self.s3.head_object(Bucket=self.bucketname, Key=self.key, VersionId=version_id)
        kwargs: dict = {
            "Bucket": self.bucketname,
            "Key": self.key,
            "CopySource": {
                "Bucket": self.bucketname,
                "Key": self.key,
                "VersionId": version_id,
            },
            "MetadataDirective": "REPLACE",
        }
        for field in (
            "ContentType",
            "ContentEncoding",
            "CacheControl",
            "ContentDisposition",
            "ContentLanguage",
            "Expires",
            "Metadata",
        ):
            if field in head:
                kwargs[field] = head[field]
        self.s3.copy_object(**kwargs)
