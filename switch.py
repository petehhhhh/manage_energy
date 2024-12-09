from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from .energy_manager import manage_energy
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from homeassistant.core import callback


async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    name = config_entry.data["host"]
    async_add_entities(
        [
            SolarCurtailmentSwitch(
                name + "_SolarCurtailment",
                config_entry.title + " Solar Curtailment",
                hub,
            ),
            AutoSwitch(name + "_Auto", config_entry.title + " Auto", hub),
        ]
    )


class SolarCurtailmentSwitch(SwitchEntity):
    """Representation of a switch for solar curtailment."""

    type = "solar curtailment"

    def __init__(self, name, title, hub):
        self._id = name
        self._state = False
        self._hub = hub

        self._name = title
        self._icon = "mdi:power-plug"
        self._available = True
        self._unique_id = f"{self._hub.hub_id}-{self._id}"
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._name,
            "manufacturer": self._hub.manufacturer,
            "model": "Energy Manager",
        }
        self.enabled_by_default = True

        self._attributes = {
            "friendly_name": self._name,
            "icon": self._icon,
            "unique_id": self._unique_id,
        }

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    @property
    def device_state_attributes(self) -> dict:
        """Return the state attributes."""
        return self._attributes

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Return true if switch is on."""
        self._state = self._hub.curtailment
        return self._state

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id

    @property
    def available(self) -> bool:
        """Return True if auto mode not enabled."""
        return True

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        self._state = True
        await self._hub.set_solar_curtailment(self._state)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        self._state = False
        await self._hub.set_solar_curtailment(self._state)
        self.async_write_ha_state()

    async def async_update(self):
        """Update the state of the switch."""
        self._state = self._hub.curtailment

    async def async_added_to_hass(self):
        """Handle when the entity is added to Home Assistant."""

        @callback
        def async_auto_switch_state_listener(event):
            """React to changes in the auto_switch state."""
            self.async_schedule_update_ha_state()

        self._hub.add_listener(async_auto_switch_state_listener)


class AutoSwitch(SwitchEntity):
    """Representation of a switch to control whether Auto mode is on and Manage Energy controls battery charge/discharge."""

    type = "Auto Power Management"

    def __init__(self, name, title, hub):
        self._id = name
        self._hub = hub
        self._state = self._hub.get_auto()
        self._name = title
        self._icon = "mdi:power-plug"
        self._available = True
        self._unique_id = f"{self._hub.hub_id}-{self._id}"
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._name,
            "manufacturer": self._hub.manufacturer,
            "model": "Energy Manager",
        }
        self.enabled_by_default = True

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    @property
    def device_state_attributes(self) -> dict:
        """Return the state attributes."""
        return self._attributes

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Return true if switch is on."""
        self._state = self._hub.get_auto()
        return self._state

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        self._state = True
        await self._hub.set_auto(self._state)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        self._state = False
        await self._hub.set_auto(self._state)
        self.async_write_ha_state()

    async def async_update(self):
        """Update the state of the switch."""
        self._state = self._hub.get_auto()
