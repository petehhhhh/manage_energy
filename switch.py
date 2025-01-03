from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
    ENTITY_ID_FORMAT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, EntityIDs
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up switches dynamically based on the SWITCHES dictionary."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    # Create entities by iterating over the SWITCHES dictionary
    entities = [
        entity_class(description, entity_id, hub)
        for entity_class, description, entity_id in SWITCHES.values()
    ]
    async_add_entities(entities)


class BaseSwitch(SwitchEntity):
    def __init__(self, entity_description, id, hub):
        self._hub = hub
        self.hass = hub._hass
        self.entity_description = entity_description
        self._attr_unique_id = id.replace(ENTITY_ID_FORMAT, "")

        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": entity_description.name,
            "manufacturer": self._hub.manufacturer,
            "model": "Energy Manager",
        }

        self._hub.add_listener(self._on_hub_state_changed)

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return True if auto mode not enabled."""
        return True

    def _on_hub_state_changed(self, new_state):
        """Handle when the hub's state changes."""
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Handle when the entity is added to Home Assistant."""

        @callback
        def async_switch_state_listener(event):
            """React to changes in the auto_switch state."""
            self.async_schedule_update_ha_state()

        self._hub.add_listener(async_switch_state_listener)


class SolarCurtailmentSwitch(BaseSwitch):
    """Representation of a switch for solar curtailment."""

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._hub.curtailment

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self._hub.set_solar_curtailment(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self._hub.set_solar_curtailment(False)
        self.async_write_ha_state()


class AutoSwitch(BaseSwitch):
    """Representation of a switch to control whether Auto mode is on and Manage Energy controls battery charge/discharge."""

    @property
    def is_on(self):
        """Return true if switch is on."""
        self._state = self._hub.get_auto()
        return self._state

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


SWITCHES: dict[str, tuple[type, SwitchEntityDescription, str]] = {
    "Curtailment": (
        SolarCurtailmentSwitch,
        SwitchEntityDescription(
            key="solar_curtailment",
            name="Solar Curtailment",
            icon="mdi:solar-power-variant-outline",
        ),
        EntityIDs.SOLAR_CURTAILMENT,
    ),
    "Auto": (
        AutoSwitch,
        SwitchEntityDescription(
            key="manage_energy_auto",
            name="Manage Energy Auto",
            icon="mdi:head-lightbulb",
        ),
        EntityIDs.AUTO,
    ),
}
