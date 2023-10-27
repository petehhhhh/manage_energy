from .const import DOMAIN, SELECT_OPTIONS
from homeassistant.components.select import SelectEntity
from .energy_manager import manage_energy


async def async_setup_entry(hass, config_entry, async_add_entities):
    hub = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([Select("PowerMode", "Power Mode", hub)])


class Select(SelectEntity):
    # define a select entity
    def __init__(self, select_id: str, name: str, hub) -> None:
        """Initialize a select entity."""
        self._id = select_id
        self._name = name
        self._hub = hub
        self._state = None
        self._options = SELECT_OPTIONS
        self._icon = "mdi:menu"
        self._unique_id = f"{self._hub.hub_id}-{self._id}"
        self._available = True
        self._enabled = True
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self._hub._name,
            "manufacturer": self._hub.manufacturer,
            "model": "Energy Manager",
        }
        self._attributes = {
            "friendly_name": self._name,
            "icon": self._icon,
            "options": self._options,
            "unique_id": self._unique_id,
        }
        self._state = self._options[0]
        self._attributes["options"] = self._options
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
    def options(self) -> list:
        """Return the list of available options."""
        return self._options

    def set_available(self, available: bool) -> None:
        """Set availability."""
        self._available = available
        self._attributes["available"] = self._available
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._state = option
        self._attributes["state"] = self._state
        self.set_available(False)
        try:
            await self._hub.set_mode(option)
        finally:
            self.set_available(True)
