"""Config flow for Hello World integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry, OptionsFlow


from .const import DOMAIN, ConfName, ConfDefaultInt, HOST_DEFAULT

_LOGGER = logging.getLogger(__name__)

# This is the schema that used to display the UI to the user. This simple
# schema has a single required host field, but it could include a number of fields
# such as username, password etc. See other components in the HA core code for
# further examples.
# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations
# At the time of writing I found the translations created by the scaffold didn't
# quite work as documented and always gave me the "Lokalise key references" string
# (in square brackets), rather than the actual translated value. I did not attempt to
# figure this out or look further into it.
# DATA_SCHEMA = vol.Schema({("host"): str}, default=HOST_DEFAULT)

DATA_SCHEMA = vol.Schema({vol.Required(f"{ConfName.HOST}", default=HOST_DEFAULT): str})


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    # This is a simple example to show an error in the UI for a short hostname
    # The exceptions are defined at the end of this file, and are used in the
    # `async_step_user` method below.
    if len(data["host"]) < 3:
        raise InvalidHost

    # Return info that you want to store in the config entry.
    # "Title" is what is displayed to the user for this hub device
    # It is stored internally in HA as part of the device config.
    # See `async_step_user` below for how this is used
    title = data["host"]

    return {"title": title}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hello World."""

    VERSION = 1
    # Pick one of the available connection classes in homeassistant/config_entries.py
    # This tells HA if it should be asking for updates, or it'll be notified of updates
    # automatically. This example uses PUSH, as the dummy hub will notify HA of
    # changes.
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow for SolarEdge Modbus Multi."""
        return EnergyManagerOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. This example provides a single form (built from `DATA_SCHEMA`),
        # and when that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                host = user_input["host"]
                host = host.replace(".", "_")
                host = host.replace(" ", "_")
                host = host.replace("-", "_")
                host = host.replace(":", "_")
                user_input["host"] = host
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidHost:
                # The error string is set here, and should be translated.
                # This example does not currently cover translations, see the
                # comments on `DATA_SCHEMA` for further details.
                # Set the error on the `host` field, not the entire form.
                errors["host"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class EnergyManagerOptionsFlowHandler(OptionsFlow):
    """Handle an options flow for SolarEdge Modbus Multi."""

    # when changing, change strings.json remember to copy to transalations and to refresh cache in safari cmd+R

    def __init__(self, config_entry: ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle the initial options flow step."""

        errors = {}

        if user_input is not None:
            if user_input[ConfName.POLLING_FREQUENCY] < 1:
                errors[ConfName.POLLING_FREQUENCY] = "invalid_scan_interval"
            elif user_input[ConfName.POLLING_FREQUENCY] > 86400:
                errors[ConfName.POLLING_FREQUENCY] = "invalid_scan_interval"
            elif user_input[ConfName.MINIMUM_MARGIN] < 0:
                errors[ConfName.MINIMUM_MARGIN] = "invalid_margin"
            elif user_input[ConfName.MINIMUM_MARGIN] > 100:
                errors[ConfName.MINIMUM_MARGIN] = "invalid_margin"
            else:
                return self.async_create_entry(title="", data=user_input)

        else:
            user_input = {
                ConfName.POLLING_FREQUENCY: self.config_entry.options.get(
                    ConfName.POLLING_FREQUENCY, ConfDefaultInt.POLLING_FREQUENCY
                ),
                ConfName.MINIMUM_MARGIN: self.config_entry.options.get(
                    ConfName.MINIMUM_MARGIN, ConfDefaultInt.MINIMUM_MARGIN
                ),
            }
        data_schema = vol.Schema(
            {
                vol.Optional(
                    f"{ConfName.POLLING_FREQUENCY}",
                    default=user_input[ConfName.POLLING_FREQUENCY],
                ): vol.Coerce(int),
                vol.Optional(
                    f"{ConfName.MINIMUM_MARGIN}",
                    default=user_input[ConfName.MINIMUM_MARGIN],
                ): vol.Coerce(int),
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=data_schema, errors=errors
        )
