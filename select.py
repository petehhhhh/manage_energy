from .const import DOMAIN, PowerSelectOptions, TeslaModeSelectOptions, EntityIDs
from homeassistant.components.select import SelectEntity, ENTITY_ID_FORMAT
from .energy_manager import manage_energy
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event


async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    name = config_entry.data["host"]
    async_add_entities(
        [
            PowerModeSelect(
                EntityIDs.MODE_SELECT,
                "Power Mode",
                hub,
            ),
            TeslaModeSelect(EntityIDs.TESLA_MODE_SELECT, "Tesla Mode", hub),
        ]
    )


class BaseSelect(SelectEntity):
    # define a select entity
    def __init__(self, id: str, name: str, hub) -> None:
        """Initialize a select entity."""
        self.entity_id = id
        self._name = name
        self._hub = hub
        self._state = None
        self._attr_icon = "mdi:menu"
        self._attr_unique_id = id.replace(ENTITY_ID_FORMAT, "")

        self._available = True
        self._enabled = True
        self._state = self._options[0]
        self._attr_options = list(self._options)

        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._name,
            "manufacturer": self._hub.manufacturer,
            "model": "Energy Manager",
        }
        super().__init__()

        async_track_state_change_event(
            hub.hass,
            [self.entity_id],  # List of entities to monitor
            hub.refresh_on_state_change,  # Call the async refresh method whenever their state changes
        )

    @property
    def name(self) -> str:
        """Return the name of the select entity."""
        return self._name

    @property
    def state(self) -> str:
        """Return the state of the entity."""
        return self._state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def options(self) -> list:
        """Return the list of available options."""
        return self._options

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    def set_available(self, available: bool) -> None:
        """Set availability."""
        self._available = available


class TeslaModeSelect(BaseSelect):
    def __init__(self, select_id: str, name: str, hub) -> None:
        """Initialize a select entity."""

        self._options = [option.value for option in TeslaModeSelectOptions]

        super().__init__(select_id, name, hub)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._state = option

        self.set_available(False)
        try:
            await self._hub.tesla.set_mode(option)
        finally:
            self.set_available(True)


class PowerModeSelect(BaseSelect):
    def __init__(self, select_id: str, name: str, hub) -> None:
        """Initialize a select entity."""

        self._options = [option.value for option in PowerSelectOptions]
        super().__init__(select_id, name, hub)
        # self._available = not self._hub.get_auto()

    @property
    def available(self) -> bool:
        # Return True if auto mode not enabled unless already been set unavailable
        # self._available = not self._hub.get_auto()
        return self._available

    def select_option(self, option: str) -> None:
        """Change the selected option."""
        self._state = option

    async def async_select_option(self, option: str) -> None:
        # used when component changes when required
        self.select_option(option)
        self.set_available(False)
        try:
            self._hub.set_mode(option)
        finally:
            self.set_available(True)

    async def async_added_to_hass(self):
        """Handle when the entity is added to Home Assistant."""

        @callback
        def async_auto_switch_state_listener(event):
            """React to changes in the auto_switch state."""
            self.async_schedule_update_ha_state()

        @callback
        def async_mode_change_listener(event):
            """React to changes in the auto_switch state."""
            self.select_option(self._hub.get_mode())
            self.async_schedule_update_ha_state()

        # Listen for changes in the auto_switch state
        self.hass.bus.async_listen("state_changed", async_auto_switch_state_listener)
        self._hub.add_listener(async_mode_change_listener)
