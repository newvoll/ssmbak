"""Preview and restore AWS SSM params backed-up by the event-driven Lambda function.

Restores SSM Parameters to their state at a given time. Preview is
just a dry run without actual restore. Latest is always relative to
the point in time (checktime). Works for just one key or a path with a
bunch. You can choose whether to operate on the path recursively
(default False).

Typical usage example (note trailing slash for path/):

from ssmbak.restore.actions import Path

from datetime import datetime, timezone

point_in_time = datetime(2023, 8, 3, 21, 9, 31, tzinfo=timezone.utc)

path = Path("/some/ssm/path/", point_in_time, "us-west-2", mys3bucket, recurse=True)

previews = path.preview()

path.restore()  #  == previews
"""

import logging
from datetime import datetime, timezone

from ssmbak.restore.aws import Resource
from ssmbak.typing import Preview, Version

logger = logging.getLogger(__name__)


class Path(Resource):
    """An s3/ssm key or a path to restore to a point in time.

    SSM Parms will be restored to their values at checktime. If params
    were deleted at that time, they will be deleted upon Path.restore().
    The lambda will back up any ssm change to exactly the same key in
    the configured s3 bucket.  Multiple keys not in the same path will
    have to instantiate a Path object for each one.

    Attributes:
      :param name: A string of the ssm/s3 key or path
      :param checktime: the point in time for which to retrieve relative latest version
      :param recurse: A boolean to operate on all paths/keys under name/
      :param versions: A cache used for preview/restore, starts empty
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        checktime: datetime,
        region: str,
        bucketname: str,
        recurse=False,
    ):
        """Initializes path/key with the region, backup bucket, and point in time.

        The bucket and params need to be accessible using the same
        region. Internally, all datetimes are tz aware, using UTC.

        Args:
          name: ssm/s3 key or path
          checktime: the point in time for which to retrieve relative latest version
          region: The AWS region for params and bucket access
          bucketname: The same bucket that the lambda writes to.
          recurse: operate on all paths/keys under name/
        """
        self.name = name  # .rstrip("/")
        self.checktime = checktime
        self.recurse = recurse
        self.versions = {}
        super().__init__(region, bucketname)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({self.name}, "
            f"{self.checktime.strftime('%Y-%m-%dT%H:%M:%SZ')}, "
            f"{self.region}, {self.bucketname})"
        )

    def get_names(self) -> list[str]:
        """Get the names of the latest versions.

        Seeds the version cache self.versions along the way.

        Returns:
          A list of version names only, e.g.

          ["/some/key", "/some/other/key"]
        """
        versions = self.get_versions()
        names = list(set(versions))
        if self.name in names and not self.recurse:  # if it's a key and not a path
            return [self.name]
        return names

    def get_versions(self) -> dict[str, Version]:
        """Grabs the verbose versions most recent relative to checktime.

        Keyed by s3/ssm key name.

        Returns:
        Returns the self.versions cache if it's not empty, populates
        it otherwise. Contains more infomration that ends up in
        preview.

          {
              "/testyssmbak/XHG0Y1": {
                  "Body": "4PPS8T",
                  "ETag": '"3149f5a99287b0e05fe34446b4fbe054"',
                  "IsLatest": False,
                  "Key": "/testyssmbak/XHG0Y1",
                  "LastModified": datetime.datetime(
                      2024, 6, 8, 21, 45, 22, tzinfo=tzutc()
                  ),
                  "Owner": {
                      "DisplayName": "webfile",
                      "ID": "029ejf2ienc09",
                  },
                  "Size": 6,
                  "StorageClass": "STANDARD",
                  "VersionId": "OMY7u3ey3H6ACQEbne96zQ",
                  "tagset": {
                      "ssmbakDescription": "fancy " "description",
                      "ssmbakTime": "1659560971",
                      "ssmbakType": "SecureString",
                  },
              }
          }

        """
        if self.versions:
            versions = self.versions
        else:
            versions = self._get_versions(
                self.name,
                self.checktime,
                recurse=self.recurse,
            )
            self.versions = versions
        return versions

    def preview(self) -> list[Preview]:
        """Shows what would be restored.

        Returns:
          A list of dicts, one for each ssm/s3 key, with concise
          information about the latest versions to be restored
          relative to checktime.

          [
              {
                  "Description": "fancy description",
                  "Modified": datetime.datetime(
                      2022, 8, 3, 21, 9, 31, tzinfo=datetime.timezone.utc
                  ),
                  "Name": "/testyssmbak/08D2SR",
                  "Type": "SecureString",
                  "Value": "C2FMGS",
              }
          ]
        """

        names = self.get_names()
        previews = [self.preview_key(name) for name in names]
        return sorted(previews, key=lambda d: d["Name"])

    def restore(self) -> list[Preview]:
        """Restore parameters to their state at time,

        It uses self.preview's returned values to actually perform the
        restore. Deleted params are handled efficiently in batches.

        Returns:
          A list of dicts, one for each ssm/s3 key, with concise
          information about the latest versions to be restored
          relative to checktime.

          [
              {
                  "Description": "fancy description",
                  "Modified": datetime.datetime(
                      2022, 8, 3, 21, 9, 31, tzinfo=datetime.timezone.utc
                  ),
                  "Name": "/testyssmbak/08D2SR",
                  "Type": "SecureString",
                  "Value": "C2FMGS",
              },
              {
                  "Description": "fancy description",
                  "Modified": datetime.datetime(
                      2022, 8, 3, 21, 9, 31, tzinfo=datetime.timezone.utc
                  ),
                  "Name": "/testyssmbak/19F3TS",
                  "Type": "SecureString",
                  "Value": "D3GNFT",
              },
          ]
        """
        params = self.preview()
        self._ssm_del_multi(
            [x["Name"] for x in params if "Deleted" in x and x["Deleted"] is True]
        )
        for param in [x for x in params if "Deleted" not in x]:
            self._restore_preview(param)
        return params

    def preview_key(self, name: str) -> Preview:
        """Shows what would be restored for the single s3/ssm key.

        Args:
          name: the s3/ssm key

        Returns:
          A dict with concise information about the key.
          {
              "Description": "fancy description",
              "Deleted": True,
              "Modified": datetime.datetime(
                  2022, 8, 3, 21, 9, 31, tzinfo=datetime.timezone.utc
              ),
              "Name": "/testyssmbak/5M9UOV",
              "Type": "SecureString",
              "Value": "318Z27",
          }
        """
        res = {"Name": name}
        version = self.get_latest_version(name)
        if "Deleted" in version:
            res["Deleted"] = True
            res["Modified"] = version["LastModified"]
        elif version:
            res["Value"] = version["Body"]
            tagset = version["tagset"]
            res["Type"] = tagset["ssmbakType"]
            res["Modified"] = datetime.fromtimestamp(
                int(tagset["ssmbakTime"]), tz=timezone.utc
            )
            if "ssmbakDescription" in tagset:
                res["Description"] = tagset["ssmbakDescription"]
        else:
            logger.warning(
                "Key %s doesn't have a version before %s", name, self.checktime
            )
        return res

    def get_latest_version(self, name: str) -> Version:
        """Gets the concise latest version of a particular s3/ssm key.

        Returns from the self.versions cache if it includes the key,
        populates it otherwise.

        Args:
          name: the s3/ssm key

        Returns:
          A dict with concise information about the key.
          {
              "Description": "fancy description",
              "Deleted": True,
              "Modified": datetime.datetime(
                  2022, 8, 3, 21, 9, 31, tzinfo=datetime.timezone.utc
              ),
              "Name": "/testyssmbak/5M9UOV",
              "Type": "SecureString",
              "Value": "318Z27",
          }
        """
        if name in self.versions:
            version = self.versions[name]
        else:
            all_versions = self._get_versions(name, self.checktime)
            try:
                version = all_versions[name]
                self.versions[name] = version
            except KeyError:
                version = {}
        try:
            if "Deleted" not in version and "Body" not in version:
                version["Body"] = self._get_version_body(name, version["VersionId"])
        except (IndexError, KeyError):
            logger.debug("No versions")
            version = {}
        return version
