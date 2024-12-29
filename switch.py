from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from .energy_manager import manage_energy
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, EntityIDs
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change


async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    name = config_entry.data["host"]
    async_add_entities(
        [
            SolarCurtailmentSwitch(
                name="Solar Curtailment",
                id=EntityIDs.SOLAR_CURTAILMENT,
                title=" Solar Curtailment",
                hub=hub,
            ),
            AutoSwitch(name + "_Auto", EntityIDs.AUTO, "Auto", hub),
        ]
    )


class SolarCurtailmentSwitch(SwitchEntity):
    """Representation of a switch for solar curtailment."""

    type = "solar curtailment"

    def __init__(self, name, id, title, hub):
        self._hub = hub
        self.name = name
        self._icon = "mdi:power-plug"
        self._available = True
        self.entity_id = id

        self.enabled_by_default = True

        self._hub.add_listener(self._on_hub_state_changed)

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._hub.curtailment

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.entity_id

    @property
    def available(self) -> bool:
        """Return True if auto mode not enabled."""
        return True

    def _on_hub_state_changed(self, new_state):
        """Handle when the hub's state changes."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self._hub.set_solar_curtailment(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self._hub.set_solar_curtailment(False)
        self.async_write_ha_state()

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

    def __init__(self, name, id, title, hub):
        self.entity_id = id
        self._hub = hub
        self._state = self._hub.get_auto()
        self._name = title
        self._icon = "mdi:power-plug"
        self._available = True
        self._unique_id = id
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._name,
            "manufacturer": self._hub.manufacturer,
            "model": "Energy Manager",
        }
        self.enabled_by_default = True

        async_track_state_change(
            hub.hass,
            [self.entity_id],  # List of entities to monitor
            hub.refresh_on_state_change,  # Call the async refresh method whenever their state changes
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.entity_id

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
        return self.entity_id

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
