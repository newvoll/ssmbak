"""Typing aliases"""

from datetime import datetime
from typing import Literal, TypedDict

from typing_extensions import NotRequired

SSMType = Literal["SecureString", "String", "StringList"]


# Version has tags in it; previews don't
class Version(TypedDict):
    Key: str
    VersionId: str
    LastModified: datetime
    Size: int
    ETag: str
    StorageClass: str
    IsLatest: bool
    tagset: dict[str, str]
    Deleted: NotRequired[bool]
    Body: NotRequired[str]


class Preview(TypedDict):
    Name: str
    Modified: datetime
    Deleted: NotRequired[bool]
    Value: NotRequired[str]
    Type: NotRequired[SSMType]
    Description: NotRequired[str]
