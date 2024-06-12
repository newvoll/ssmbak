"""Typing aliases"""

from datetime import datetime
from typing import Union

# Version has tags in it; previews don't
Version = dict[str, Union[str, datetime, dict[str, str]]]
# But pytype can't account for that, so dict is included in possibles
Preview = dict[str, Union[str, datetime, bool, dict[str, str]]]
