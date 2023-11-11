"""Platform for sensor integration."""
# This file shows the setup for the sensors associated with the cover.
# They are setup in the same way with the call to the async_setup_entry function
# via HA from the module __init__. Each sensor has a device_class, this tells HA how
# to display it in the UI (for know types). The unit_of_measurement property tells HA
# what the unit is, so it can display the correct range. For predefined types (such as
# battery), the unit_of_measurement should match what's expected.
import random
from homeassistant.components.sensor import (
    SensorEntity,)
from homeassistant.helpers.restore_state import RestoreEntity


from .const import DOMAIN


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities([StatusBase(config_entry.data["host"] + "_status", f"{config_entry.title} Status", config_entry, hub),
                        #                      SensorBase(
                        #    config_entry.data["host"] + "_history2", f"{config_entry.title} History", config_entry, hub)
                        ])


class SensorBase(SensorEntity, RestoreEntity):
    """Base representation of a Hello World Sensor."""

    should_poll = False

    def __init__(self, name, friendly_name, config_entry, hub) -> None:
        """Initialize the sensor."""
        self._hub = hub
        self._unique_id = name
        self._name = friendly_name
        self._icon = "mdi:gauge-low"

        self._config_entry = config_entry

        # The name of the entity
        self._attr_name = self._name

        self._state = hub.state
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._hub.name,
            "manufacturer": hub.manufacturer,
            "model": "Energy Manager",
        }
        self._attributes = {
            "friendly_name": self._name,
            "icon": self._icon,
            "unique_id": self._unique_id,
        }

        self._attributes["icon"] = self._icon
        self._attributes["friendly_name"] = self._name
        self._attributes["unique_id"] = self._unique_id
        self._attributes["device_info"] = self._device_info
        self._attributes["available"] = True
        self._attributes["state"] = self._state

        super().__init__()

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._state = last_state.state

    @property
    def name(self) -> str:
        """Return the name of the select entity."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        return self._icon

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        return self._state

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def device_state_attributes(self) -> dict:
        """Return the state attributes."""
        return self._attributes

    @property
    def config_entry_id(self):
        return self._config_entry.entry_id

    @property
    def config_entry_name(self):
        return self._config_entry.data["name"]


class StatusBase(SensorEntity):
    """Base representation of a Hello World Sensor."""
    should_poll = False

    def __init__(self, name, friendly_name, config_entry, hub) -> None:
        """Initialize the sensor."""
        self._hub = hub
        self._unique_id = name
        self._name = friendly_name
        self._icon = "mdi:gauge-low"

        self._config_entry = config_entry

        # The name of the entity
        self._attr_name = self._name

        self._state = hub.state
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._hub.name,
            "manufacturer": hub.manufacturer,
            "model": "Energy Manager",
        }
        self._attributes = {
            "friendly_name": self._name,
            "icon": self._icon,
            "unique_id": self._unique_id,
        }

        self._attributes["icon"] = self._icon
        self._attributes["friendly_name"] = self._name
        self._attributes["unique_id"] = self._unique_id
        self._attributes["device_info"] = self._device_info
        self._attributes["available"] = True
        self._attributes["state"] = self._state
        self._hub.add_listener(self._on_hub_state_changed)
        super().__init__()

    def _on_hub_state_changed(self, new_state):
        """Handle when the hub's state changes."""
        self._state = str(new_state)
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return the name of the select entity."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        return self._icon

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        self._state = str(self._hub.state)
        self._attributes["state"] = self._hub.state
        return self._state

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def device_state_attributes(self) -> dict:
        """Return the state attributes."""
        return self._attributes

    @property
    def config_entry_id(self):
        return self._config_entry.entry_id

    @property
    def config_entry_name(self):
        return self._config_entry.data["name"]
