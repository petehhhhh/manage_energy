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

from .const import DOMAIN, EntityIDs

from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NAME,
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up switches dynamically based on the SWITCHES dictionary."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    # Create entities by iterating over the SWITCHES dictionary
    entities = [
        entity_class(description, entity_id, hub)
        for entity_class, description, entity_id in SENSORS.values()
    ]
    async_add_entities(entities)


class SensorBase(SensorEntity, RestoreEntity):
    """SensorBase for Manage Energy."""

    def __init__(self, entity_description: SensorEntityDescription, id, hub) -> None:
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
        self._attr_unique_id = id

        self._hub.add_listener(self._on_hub_state_changed)

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

    @property
    def native_value(self) -> str:
        """Return the state of the entity."""
        return str(self._hub.state)


class HistoryBase(SensorBase, RestoreEntity):
    def __init__(self, entity_description: SensorEntityDescription, id, hub) -> None:
        """Initialize the sensor."""
        self._state = None
        hub.forecasts.add_listener(self._on_hub_state_changed)
        super().__init__(entity_description, id, hub)

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


class ForecastBase(HistoryBase, SensorBase):
    """The current forecast"""

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


SENSORS: dict[str, SensorEntityDescription] = {
    "status": (
        StatusBase,
        SensorEntityDescription(
            key="manage-energy-status",
            translation_key="status",
            name="Manage Energy Status",
            icon="mdi:gauge-low",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        EntityIDs.STATUS,
    ),
    "history": (
        HistoryBase,
        SensorEntityDescription(
            key="manage-energy-history",
            translation_key="history",
            name="Manage Energy History",
            icon="mdi:gauge-low",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        EntityIDs.HISTORY,
    ),
    "forecast": (
        ForecastBase,
        SensorEntityDescription(
            key="manage-energy-forecast",
            translation_key="forecast",
            name="Manage Energy Forecast",
            icon="mdi:gauge-low",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        EntityIDs.FORECAST,
    ),
}
