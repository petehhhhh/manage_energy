"""Pete's energy integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .energy_manager import manage_energy
from .const import DOMAIN, ConfName, ConfDefaultInt
from homeassistant.helpers.event import async_track_state_change

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS: list[str] = ["select", "switch", "sensor", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    poll_frequency = entry.options.get(
        ConfName.POLLING_FREQUENCY, ConfDefaultInt.POLLING_FREQUENCY
    )
    minimum_margin = entry.options.get(
        ConfName.MINIMUM_MARGIN, ConfDefaultInt.MINIMUM_MARGIN
    )

    # Ensure hass.data is a dictionary
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    hub = manage_energy(hass, entry.data["host"], poll_frequency, minimum_margin)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    async def handle_manage_energy_service(call):
        """Handle the service call."""
        await hub.handle_manage_energy()

    # Register the service
    hass.services.async_register(DOMAIN, "refresh", handle_manage_energy_service)

    hass.bus.async_listen_once("homeassistant_started", handle_manage_energy_service)

    # Forward the setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    async_track_state_change(
        hass,
        ["sensor.energy_usage", "sensor.price"],  # List of entities to monitor
        hub.refresh,  # Call the async refresh method whenever their state changes
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details. Also is called when updating the config entry, so needs to handle
    # reloading itself in that case.

    hub = hass.data.setdefault(DOMAIN, {})[entry.entry_id]
    await hub.stop_poll()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update."""
    # await hass.config_entries.async_reload(entry.entry_id)
    hub = hass.data.setdefault(DOMAIN, {})[entry.entry_id]
    await hub.update_poll_frequency(
        entry.options.get(ConfName.POLLING_FREQUENCY, ConfDefaultInt.POLLING_FREQUENCY)
    )

    hub.minimum_margin = entry.options.get(
        ConfName.MINIMUM_MARGIN, ConfDefaultInt.MINIMUM_MARGIN
    )
    hub.set_cheap_price(
        entry.options.get(ConfName.CHEAP_PRICE, ConfDefaultInt.CHEAP_PRICE)
    )
