"""Research governance package.

Holds machine-enforced governance decisions (e.g. lane suspensions) that gate what
research runners are allowed to do. Kept separate from research code so policy is
auditable and testable on its own.
"""

from . import lane_suspension  # noqa: F401
from . import lane_reopening  # noqa: F401
