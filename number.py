from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    RestoreNumber,
    ENTITY_ID_FORMAT,
)
from homeassistant.const import CONF_NAME
from homeassistant.components.number.const import NumberDeviceClass
from .const import DOMAIN, EntityIDs
from homeassistant.helpers.event import async_track_state_change


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up numbers dynamically based on the NUMBERS dictionary."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    # Create entities dynamically
    entities = [
        entity_class(description, unique_id, hub)
        for entity_class, description, unique_id in NUMBERS.values()
    ]
    async_add_entities(entities)


class BaseNumberEntity(RestoreNumber):
    """Representation of a custom number entity."""

    def __init__(self, entity_description, unique_id, hub):
        super().__init__()  # Initialize the base class
        self.entity_description = entity_description

        # Assign unique ID for entity registry
        self._attr_unique_id = unique_id.replace(ENTITY_ID_FORMAT, "")
        self._attr_name = entity_description.name

        # Set initial value
        # self._attr_native_value = hub.cheap_price

        # Store hub reference
        self._hub = hub
        self._attr_mode = "box"

        # Device info for integration
        self._device_info = {
            "identifiers": {(DOMAIN, self._hub.hub_id)},
            "name": entity_description.name,
            "manufacturer": hub.manufacturer,
            "model": "Energy Manager",
        }

    @property
    def native_value(self) -> float | None:
        """Return the value reported by the number."""
        return self._attr_native_value

    async def async_added_to_hass(self):
        """Handle entity which is added to Home Assistant."""
        await super().async_added_to_hass()  # Call parent implementation

        # Attempt to restore the last known state
        last_state = await self.async_get_last_number_data()
        if last_state and last_state.native_value not in (None, "unknown"):
            self._attr_native_value = float(last_state.native_value)
            self._hub.cheap_price = self._attr_native_value
        else:
            # Write the current state if no previous state exists
            self._attr_native_value = self._hub.cheap_price

        # Ensure the state is written to Home Assistant
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        self._attr_native_value = value

        self._hub.cheap_price = value  # Update the hub value
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict:
        """Return device information."""
        return self._device_info


NUMBERS: dict[str, NumberEntityDescription] = {
    "CheapGrid": (
        BaseNumberEntity,
        NumberEntityDescription(
            key="cheap_charge_price",
            device_class=NumberDeviceClass.MONETARY,
            name="Cheap Charge Price",
            icon="mdi:currency-usd",
            native_max_value=1,
            native_min_value=0,
            native_step=0.01,
            step=0.01,
            mode="box",
            native_unit_of_measurement="$",
        ),
        EntityIDs.MAX_PRICE,
    )
}
