"""The admin panel's notifications (Super Admin 11.1, Admin 8.1): the bell, its emails and the
preferences.

Other code alerts the team with `notify_admins(db, kind, data, target_id=...)` (also importable
from here, as app/admin/common.py does); the kinds are in `kinds.py`.
"""

from app.admin.notifications.service import notify_admins

__all__ = ["notify_admins"]
