"""Platform for sensor integration."""

# This file shows the setup for the sensors associated with the cover.
# They are setup in the same way with the call to the async_setup_entry function
# via HA from the module __init__. Each sensor has a device_class, this tells HA how
# to display it in the UI (for know types). The unit_of_measurement property tells HA
# what the unit is, so it can display the correct range. For predefined types (such as
# battery), the unit_of_measurement should match what's expected.
import random
from homeassistant.components.sensor import (
    Entity,
    SensorEntity,
    SensorDeviceClass,
    SensorEntityDescription,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN

from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
)


SENSORS: dict[str, SensorEntityDescription] = {
    "status": SensorEntityDescription(
        key="manage-energy-status",
        translation_key="status",
        name="Status",
        icon="mdi:gauge-low",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "history": SensorEntityDescription(
        key="manage-energy-history",
        translation_key="history",
        name="History",
        icon="mdi:gauge-low",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "forecast": SensorEntityDescription(
        key="manage-energy-forecast",
        translation_key="forecast",
        name="Forecast",
        icon="mdi:gauge-low",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        [
            StatusBase(SENSORS["status"], config_entry, hub),
            HistoryBase(SENSORS["history"], config_entry, hub),
            Forecast(SENSORS["forecast"], config_entry, hub),
        ]
    )


class SensorBase(SensorEntity, RestoreEntity):
    """SensorBase for Manage Energy."""

    def __init__(
        self, entity_description: SensorEntityDescription, config_entry, hub
    ) -> None:
        """Initialize the sensor."""
        super().__init__()
        self._hub = hub

        self.entity_description = entity_description

        self._attributes = {}
        self._attr_extra_state_attributes = {}
        self._attr_device_info = {
            ATTR_IDENTIFIERS: {(DOMAIN, self._hub.hub_id)},
            ATTR_NAME: self._hub.name,
            ATTR_MANUFACTURER: hub.manufacturer,
            ATTR_MODEL: "Energy Model",
        }
        self._attr_unique_id = entity_description.key
        self._unique_id = entity_description.key

    @property
    def should_poll(self) -> bool:
        """Return if the sensor should poll."""
        return False

    def _on_hub_state_changed(self, new_state):
        """Handle when the hub's state changes."""
        self._state = str(new_state)
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        """Return the name of the select entity."""
        return self.entity_description.name

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        return self._state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True


class StatusBase(SensorBase):
    should_poll = False

    def __init__(self, entity_description, config_entry, hub) -> None:
        """Initialize the sensor."""

        self._state = hub.state

        super().__init__(entity_description, config_entry, hub)

        self._hub.add_listener(self._on_hub_state_changed)

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        self._state = str(self._hub.state)
        self._attributes["state"] = self._hub.state
        return self._state


class HistoryBase(SensorBase, RestoreEntity):
    def __init__(
        self, entity_description: SensorEntityDescription, config_entry, hub
    ) -> None:
        """Initialize the sensor."""

        hub.forecasts.add_listener(self._on_hub_state_changed)
        self._state = None

        super().__init__(entity_description, config_entry, hub)

    def _on_hub_state_changed(self, new_state):
        """Handle when the hub's state changes."""
        self._state = str(len(self._hub.forecasts.history))
        self._attributes["state"] = self._state
        self._attr_extra_state_attributes["history"] = self._hub.forecasts.history

        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._state = last_state.state

        if self._state != None and "history" in last_state.attributes:
            self._hub.history = last_state.attributes["history"]
            self._attr_extra_state_attributes["history"] = self._hub.history
        else:
            self._hub.history = []
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        self._state = str(len(self._hub.forecasts.history))
        self._attr_extra_state_attributes["history"] = self._hub.forecasts.history

        return self._state

    @property
    def extra_state_attributes(self):
        return self._attr_extra_state_attributes


class Forecast(HistoryBase, SensorBase):
    """The current forecast"""

    def __init__(
        self, entity_description: SensorEntityDescription, config_entry, hub
    ) -> None:
        self._unique_id = entity_description.key
        super().__init__(entity_description, config_entry, hub)

    def _on_hub_state_changed(self, new_state):
        """Handle when the hub's state changes."""
        self._state = str(len(self._hub.forecasts.forecast))
        self._attributes["state"] = self._state
        self._attr_extra_state_attributes["forecast"] = self._hub.forecasts.forecast

        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._state = last_state.state

        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        self._state = str(len(self._hub.forecasts.forecast))
        self._attr_extra_state_attributes["forecast"] = self._hub.forecasts.forecast

        return self._state
