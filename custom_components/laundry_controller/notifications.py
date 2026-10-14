"""Phone notification formatting and delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .const import ACTION_HANG_DRY, ACTION_MARK_DONE, DOMAIN
from .reminders import is_overdue
from .state_machine import Appliance, LaundryStateMachine, Notice, Phase

_LOGGER = logging.getLogger(__name__)

NOTIFY_DOMAIN = "notify"
MOBILE_APP_PREFIX = "mobile_app_"
CLEAR_NOTIFICATION = "clear_notification"
CALL_TIMEOUT = 30

TITLE = "Laundry"
LABEL_HANG_DRY = "Hang Dry (Done)"
LABEL_MARK_DONE = "Mark as Done"


@dataclass(frozen=True, slots=True)
class PhoneMessage:
    """A notification ready to send."""

    title: str
    message: str
    tag: str
    actions: tuple[tuple[str, str], ...] = ()
    importance: str | None = None


def action_id(action: str, entry_id: str) -> str:
    """Build an instance-scoped action identifier."""
    return f"{action}:{entry_id}"


def parse_action(value: Any) -> tuple[str, str] | None:
    """Split an action identifier into (action, entry_id)."""
    if not isinstance(value, str) or ":" not in value:
        return None
    action, entry_id = value.split(":", 1)
    if action not in (ACTION_HANG_DRY, ACTION_MARK_DONE):
        return None
    return action, entry_id


def state_tag(entry_id: str) -> str:
    """Tag for the current-state notification category."""
    return f"{DOMAIN}_{entry_id}_state"


def reminder_tag(entry_id: str) -> str:
    """Tag for the reminder notification category."""
    return f"{DOMAIN}_{entry_id}_reminder"


def format_age(delta: timedelta) -> str:
    """Format an elapsed time like "1 h 5 min"."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "less than a minute"
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    if hours:
        return f"{hours} h"
    return f"{minutes} min"


def build_finished(
    kind: Notice, machine: LaundryStateMachine, entry_id: str
) -> PhoneMessage:
    """Build the washer/dryer finished notification."""
    if kind is Notice.WASHER_FINISHED:
        if machine.dryer.phase is Phase.RUNNING:
            message = "Washer finished while the dryer is running."
        else:
            message = "Washer finished! Move clothes to the dryer."
        return PhoneMessage(
            title=TITLE,
            message=message,
            tag=state_tag(entry_id),
            actions=((action_id(ACTION_HANG_DRY, entry_id), LABEL_HANG_DRY),),
        )
    message = "Dryer finished. Laundry is ready."
    if machine.washer.phase is Phase.DONE:
        message += " The washer is also done."
    elif machine.washer.phase is Phase.RUNNING:
        message += " The washer is still running."
    return PhoneMessage(
        title=TITLE,
        message=message,
        tag=state_tag(entry_id),
        actions=((action_id(ACTION_MARK_DONE, entry_id), LABEL_MARK_DONE),),
    )


def build_reminder(
    machine: LaundryStateMachine,
    appliances: list[Appliance],
    now: datetime,
    overdue_after: timedelta,
    entry_id: str,
) -> PhoneMessage:
    """Build a reminder covering the waiting appliances."""
    overdue = any(is_overdue(machine, a, now, overdue_after) for a in appliances)
    lines = []
    for appliance in appliances:
        finished = machine.records[appliance].finished_at
        name = appliance.value.capitalize()
        if finished is None:
            lines.append(f"{name} is done.")
        else:
            lines.append(f"{name} finished {format_age(now - finished)} ago.")
    return PhoneMessage(
        title="OVERDUE: Laundry!" if overdue else "Laundry Reminder",
        message=" ".join(lines),
        tag=reminder_tag(entry_id),
        actions=((action_id(ACTION_MARK_DONE, entry_id), LABEL_MARK_DONE),),
        importance="high" if overdue else "default",
    )


class Notifier:
    """Deliver notifications to the configured notify services.

    Mobile-app services get tags, actions, importance and clear commands. Other
    notify services only receive title and message, and never "clear" texts.
    Delivery failures are logged and never raised.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        entry_title: str,
        recipients: list[str],
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.entry_id = entry_id
        self.entry_title = entry_title
        self.recipients = [r.removeprefix(f"{NOTIFY_DOMAIN}.") for r in recipients]
        self.last_error: str | None = None

    async def async_send(self, msg: PhoneMessage) -> None:
        """Send a notification to every recipient."""
        await asyncio.gather(
            *(
                self._async_call(service, self._payload(service, msg))
                for service in self.recipients
            )
        )

    async def async_clear(self, tag: str) -> None:
        """Clear a notification category on every mobile-app recipient."""
        await asyncio.gather(
            *(
                self._async_call(
                    service, {"message": CLEAR_NOTIFICATION, "data": {"tag": tag}}
                )
                for service in self.recipients
                if service.startswith(MOBILE_APP_PREFIX)
            )
        )

    @staticmethod
    def _payload(service: str, msg: PhoneMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": msg.title, "message": msg.message}
        if service.startswith(MOBILE_APP_PREFIX):
            data: dict[str, Any] = {"tag": msg.tag}
            if msg.actions:
                data["actions"] = [
                    {"action": action, "title": title} for action, title in msg.actions
                ]
            if msg.importance:
                data["importance"] = msg.importance
            payload["data"] = data
        return payload

    async def _async_call(self, service: str, payload: dict[str, Any]) -> None:
        issue_id = f"missing_notify_{self.entry_id}_{service}"
        if not self.hass.services.has_service(NOTIFY_DOMAIN, service):
            _LOGGER.warning(
                "Notify service notify.%s is not available; notification skipped",
                service,
            )
            self.last_error = f"notify.{service} not found"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_notify_service",
                translation_placeholders={
                    "service": f"notify.{service}",
                    "name": self.entry_title,
                },
            )
            return
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        try:
            async with asyncio.timeout(CALL_TIMEOUT):
                await self.hass.services.async_call(
                    NOTIFY_DOMAIN, service, payload, blocking=True
                )
        except (HomeAssistantError, TimeoutError, vol.Invalid) as err:
            _LOGGER.error("Sending notification via notify.%s failed: %s", service, err)
            self.last_error = f"notify.{service}: {err}"
        except Exception as err:
            _LOGGER.exception(
                "Unexpected error sending notification via notify.%s", service
            )
            self.last_error = f"notify.{service}: {err}"
