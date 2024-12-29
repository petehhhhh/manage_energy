from homeassistant.components.number import NumberEntity
from homeassistant.const import CONF_NAME
from .const import DOMAIN
from homeassistant.helpers.event import async_track_state_change


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up number entities for the integration."""
    hub = hass.data[DOMAIN][config_entry.entry_id]
    entities = [
        MyNumberEntity(
            name="Cheap Charge Price",
            id="number.cheap_charge_price",
            min_value=0,
            max_value=100,
            step=1,
            hub=hub,
        )
    ]
    async_add_entities(entities)


class MyNumberEntity(NumberEntity):
    """Representation of a custom number entity."""

    def __init__(
        self, name: str, id: str, min_value: float, max_value: float, step: float, hub
    ):
        self.name = name
        self.native_value = int(hub.cheap_price)
        self._attr_min_value = min_value
        self._attr_max_value = max_value
        self._attr_step = step
        self._attr_unique_id = id
        self.entity_id = id

        self._attr_mode = "box"  # Set mode to 'box' for text entry
        self._hub = hub

        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": self.name,
            "manufacturer": hub.manufacturer,
            "model": "Energy Manager",
        }
        super().__init__()

        async_track_state_change(
            hub.hass,
            [self.entity_id],  # List of entities to monitor
            hub.refresh_on_state_change,  # Call the async refresh method whenever their state changes
        )

    @property
    def device_info(self) -> dict:
        """Return device information about this entity."""
        return self._device_info

    def set_native_value(self, value: float) -> None:
        """Set new value."""
        if self._attr_min_value <= value <= self._attr_max_value:
            self.native_value = int(value)
            self._hub.cheap_price = float(value) / 100
            self.schedule_update_ha_state()
