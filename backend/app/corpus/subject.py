"""Does an indexed image actually show the domain's subject?

The lens model returns null for an attribute it cannot see. When almost nothing could be read
(an animal, packaging, a shop logo found by a keyword search), the image is not a usable
reference: no protection can be checked on it, so it would only ever land in Needs review.
"""

from collections.abc import Iterable
from typing import Any

# below this share of readable lens attributes the subject counts as absent: on the first real
# corpus, 0-3 of 14 readable were off-subject images or unreadable toys; real subjects start at 4
MIN_READABLE_SHARE = 0.25

PRESENT, ABSENT = "present", "absent"


def subject_status(values: Iterable[Any]) -> str | None:
    """'present' / 'absent' from the extracted attribute values; None when nothing was extracted."""
    vals = list(values)
    if not vals:
        return None
    readable = sum(v is not None for v in vals)
    return PRESENT if readable >= MIN_READABLE_SHARE * len(vals) else ABSENT
