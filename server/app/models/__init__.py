"""模型登记处：全部模型在此串起来 import（漏一个 = Alembic 看不见的幽灵表）。

新增模型文件必须同步加进本文件——checklist 项。
"""

from app.models.base import Base
from app.models.app_user import AppUser
from app.models.calendar_config import CalendarConfig
from app.models.command import Command
from app.models.device import Device
from app.models.kb_document import KbDocument
from app.models.material import Material
from app.models.material_vector import MaterialVector
from app.models.meeting import Meeting
from app.models.room import Room
from app.models.upload_token import UploadToken

__all__ = [
    "Base",
    "AppUser",
    "CalendarConfig",
    "Command",
    "Device",
    "KbDocument",
    "Material",
    "MaterialVector",
    "Meeting",
    "Room",
    "UploadToken",
]
