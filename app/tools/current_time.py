from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel

from app.tools.base import ToolContext, ToolSpec

_TIMEZONES: dict[str, timezone] = {
    "UTC": UTC,
    "Asia/Shanghai": timezone(timedelta(hours=8), name="Asia/Shanghai"),
}


class CurrentTimeArgs(BaseModel):
    timezone: Literal["UTC", "Asia/Shanghai"] = "UTC"


async def current_time(context: ToolContext, args: CurrentTimeArgs) -> str:
    return datetime.now(_TIMEZONES[args.timezone]).isoformat(timespec="seconds")


def build_current_time_tool() -> ToolSpec:
    return ToolSpec(
        name="current_time",
        description="Return the current date and time in UTC or Asia/Shanghai.",
        args_model=CurrentTimeArgs,
        handler=current_time,
    )
