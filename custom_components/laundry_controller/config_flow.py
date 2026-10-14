"""Config and options flows for Laundry Controller."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING,
    CONF_ON_AIR_ENTITY,
    CONF_ON_AIR_UNAVAILABLE,
    CONF_OVERDUE_AFTER,
    CONF_RECIPIENTS,
    CONF_RECONNECT_GRACE,
    CONF_REMINDER_END,
    CONF_REMINDER_INTERVAL,
    CONF_REMINDER_START,
    CONF_TTS_LANGUAGE,
    CONF_TTS_LED_BRIGHTNESS,
    CONF_TTS_LED_COLOR,
    CONF_TTS_MAX_LIGHT_DURATION,
    CONF_TTS_MESSAGES,
    CONF_TTS_SCRIPT,
    CONF_TTS_SPEAKER_DEVICE,
    CONF_TTS_VOICE,
    CONF_TTS_VOLUME,
    CONF_WASHER_RUNNING,
    DEFAULT_NAME,
    DEFAULT_OPTIONS,
    DOMAIN,
    ON_AIR_ANNOUNCE,
    ON_AIR_SUPPRESS,
    SENSOR_KEYS,
)

# Notify services that cannot deliver to a phone and are hidden from the list.
EXCLUDED_NOTIFY_SERVICES = {"send_message", "persistent_notification", "notify"}

BINARY_SENSOR_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=BINARY_SENSOR_DOMAIN)
)


def _sensor_schema() -> dict[vol.Marker, Any]:
    return {vol.Required(key): BINARY_SENSOR_SELECTOR for key in SENSOR_KEYS}


def _validate_sensors(user_input: dict[str, Any]) -> dict[str, str]:
    values = [user_input[key] for key in SENSOR_KEYS]
    if len(set(values)) != len(values):
        return {"base": "duplicate_entities"}
    return {}


def _recipient_selector(
    hass: HomeAssistant, current: list[str]
) -> selector.SelectSelector:
    services = {
        name
        for name in hass.services.async_services_for_domain("notify")
        if name not in EXCLUDED_NOTIFY_SERVICES
    }
    services.update(current)
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sorted(services),
            multiple=True,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _notification_schema(hass: HomeAssistant, current: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_RECIPIENTS): _recipient_selector(hass, current),
            vol.Optional(
                CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING
            ): selector.BooleanSelector(),
        }
    )


ANNOUNCEMENT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TTS_SCRIPT): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="script")
        ),
        vol.Optional(CONF_TTS_SPEAKER_DEVICE): selector.DeviceSelector(),
        vol.Optional(CONF_ON_AIR_ENTITY): selector.EntitySelector(),
        vol.Required(CONF_ON_AIR_UNAVAILABLE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[ON_AIR_SUPPRESS, ON_AIR_ANNOUNCE],
                translation_key=CONF_ON_AIR_UNAVAILABLE,
                mode=selector.SelectSelectorMode.LIST,
            )
        ),
        vol.Required(CONF_TTS_MESSAGES): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
        vol.Required(CONF_TTS_LANGUAGE): selector.TextSelector(),
        vol.Required(CONF_TTS_VOICE): selector.TextSelector(),
        vol.Required(CONF_TTS_VOLUME): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=1, step=0.05, mode=selector.NumberSelectorMode.SLIDER
            )
        ),
        vol.Required(CONF_TTS_LED_COLOR): selector.ColorRGBSelector(),
        vol.Required(CONF_TTS_LED_BRIGHTNESS): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER
            )
        ),
        vol.Required(CONF_TTS_MAX_LIGHT_DURATION): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=600,
                step=1,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)

REMINDER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REMINDER_INTERVAL): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=240,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_REMINDER_START): selector.TimeSelector(),
        vol.Required(CONF_REMINDER_END): selector.TimeSelector(),
        vol.Required(CONF_OVERDUE_AFTER): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=1440,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)

ADVANCED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RECONNECT_GRACE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=1800,
                step=1,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)

# Keys that are optional in a step and must be removed when left empty.
OPTIONAL_KEYS = {
    "notifications": (CONF_RECIPIENTS,),
    "announcements": (CONF_TTS_SCRIPT, CONF_TTS_SPEAKER_DEVICE, CONF_ON_AIR_ENTITY),
}
INT_KEYS = (
    CONF_REMINDER_INTERVAL,
    CONF_OVERDUE_AFTER,
    CONF_RECONNECT_GRACE,
    CONF_TTS_LED_BRIGHTNESS,
    CONF_TTS_MAX_LIGHT_DURATION,
)


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """NumberSelector returns floats; store whole-number settings as int."""
    return {
        key: int(value) if key in INT_KEYS else value
        for key, value in user_input.items()
    }


class LaundryControllerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Laundry Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._data: dict[str, Any] = {}
        self._title = DEFAULT_NAME

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the appliance sensors."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_WASHER_RUNNING: user_input[CONF_WASHER_RUNNING]}
            )
            if not (errors := _validate_sensors(user_input)):
                self._title = user_input[CONF_NAME]
                self._data = {key: user_input[key] for key in SENSOR_KEYS}
                return await self.async_step_features()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
                **_sensor_schema(),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose optional notifications and announcements."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._title,
                data=self._data,
                options={**DEFAULT_OPTIONS, **user_input},
            )
        schema = vol.Schema(
            {
                vol.Optional(CONF_RECIPIENTS): _recipient_selector(self.hass, []),
                vol.Optional(CONF_TTS_SCRIPT): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="script")
                ),
                vol.Optional(CONF_TTS_SPEAKER_DEVICE): selector.DeviceSelector(),
                vol.Optional(CONF_ON_AIR_ENTITY): selector.EntitySelector(),
            }
        )
        return self.async_show_form(step_id="features", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the appliance sensors."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None and not (errors := _validate_sensors(user_input)):
            # The update listener reloads the entry.
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, **user_input}
            )
            return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_sensor_schema()), user_input or dict(entry.data)
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LaundryOptionsFlow:
        """Return the options flow."""
        return LaundryOptionsFlow()


class LaundryOptionsFlow(OptionsFlow):
    """Options menu: notifications, announcements, reminders, advanced."""

    @property
    def _options(self) -> dict[str, Any]:
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["notifications", "announcements", "reminders", "advanced"],
        )

    def _save(self, step: str, user_input: dict[str, Any]) -> ConfigFlowResult:
        options = self._options
        for key in OPTIONAL_KEYS.get(step, ()):
            options.pop(key, None)
        options.update(_normalize(user_input))
        return self.async_create_entry(data=options)

    def _form(self, step: str, schema: vol.Schema) -> ConfigFlowResult:
        return self.async_show_form(
            step_id=step,
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Phone notification options."""
        if user_input is not None:
            return self._save("notifications", user_input)
        schema = _notification_schema(self.hass, self._options[CONF_RECIPIENTS])
        return self._form("notifications", schema)

    async def async_step_announcements(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Smart-speaker announcement options."""
        if user_input is not None:
            return self._save("announcements", user_input)
        return self._form("announcements", ANNOUNCEMENT_SCHEMA)

    async def async_step_reminders(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reminder options."""
        if user_input is not None:
            return self._save("reminders", user_input)
        return self._form("reminders", REMINDER_SCHEMA)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Advanced options."""
        if user_input is not None:
            return self._save("advanced", user_input)
        return self._form("advanced", ADVANCED_SCHEMA)
