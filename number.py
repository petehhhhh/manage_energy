from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    RestoreNumber,
)
from homeassistant.const import CONF_NAME
from .const import DOMAIN
from homeassistant.helpers.event import async_track_state_change
from .const import EntityIDs


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up switches dynamically based on the SWITCHES dictionary."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    # Create entities by iterating over the SWITCHES dictionary
    entities = [
        entity_class(description, entity_id, hub)
        for entity_class, description, entity_id in NUMBERS.values()
    ]
    async_add_entities(entities)


class BaseNumberEntity(NumberEntity):
    """Representation of a custom number entity."""

    def __init__(self, entity_description, id, hub):
        self.entity_description = entity_description

        self.entity_id = id
        self._attr_unique_id = id

        self._attr_mode = "box"  # Set mode to 'box' for text entry
        self._hub = hub
        self._attr_native_value = hub.cheap_price

        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": entity_description.name,
            "manufacturer": hub.manufacturer,
            "model": "Energy Manager",
        }

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
        self.native_value = int(value)
        self._hub.cheap_price = float(value) / 100
        self.async_write_ha_state


NUMBERS: dict[str, NumberEntityDescription] = {
    "CheapGrid": (
        BaseNumberEntity,
        NumberEntityDescription(
            key="cheap_charge_price",
            name="Cheap Charge Price",
            icon="mdi:currency-usd",
            native_max_value=100,
            native_min_value=0,
            native_step=1,
            native_unit_of_measurement="c",
        ),
        EntityIDs.MAX_PRICE,
    )
}
