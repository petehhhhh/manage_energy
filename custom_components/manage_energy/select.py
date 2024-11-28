from .const import DOMAIN, PowerSelectOptions, TeslaModeSelectOptions
from homeassistant.components.select import SelectEntity
from .energy_manager import manage_energy


async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    name = config_entry.data["host"]
    async_add_entities([PowerModeSelect(name + "_PowerMode", config_entry.title + " Power Mode", hub),
                        TeslaModeSelect(name + " _TeslaMode", config_entry.title + " Tesla Mode", hub)])


class BaseSelect(SelectEntity):
    # define a select entity
    def __init__(self, select_id: str, name: str, hub) -> None:
        """Initialize a select entity."""
        self._id = select_id
        self._name = name
        self._hub = hub
        self._state = None
        self._icon = "mdi:menu"
        self._unique_id = f"{self._hub.hub_id}-{self._id}"
        self._available = self._hub.get_auto()
        self._enabled = True
        self._state = self._options[0]
        self._attr_options = list(self._options)
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
        self._attributes["available"] = self._available
        self._attributes["state"] = self._state

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
    def state(self) -> str:
        """Return the state of the entity."""
        return self._state

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

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

    @property
    def options(self) -> list:
        """Return the list of available options."""
        return self._options

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

        self._attributes["state"] = self._state
        self.set_available(False)
        try:
            await self._hub.set_tesla_mode(option)
        finally:
            self.set_available(True)


class PowerModeSelect(BaseSelect):
    def __init__(self, select_id: str, name: str, hub) -> None:
        """Initialize a select entity."""

        self._options = [option.value for option in PowerSelectOptions]
        super().__init__(select_id, name, hub)

    @property
    def available(self) -> bool:
    # Return True if auto mode not enable...
        if set
        self._available = not self._hub.get_auto()
        return self._available

    
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._state = option
        self._attributes["state"] = self._state
        self.set_available(False)
        try:
            await self._hub.set_mode(option)
        finally:
            self.set_available(True)
