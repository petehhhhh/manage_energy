"""A demonstration 'hub' that connects several devices."""
from __future__ import annotations
from .const import DOMAIN

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
# This dummy hub always returns 3 rollers.
import asyncio
import random

from homeassistant.core import HomeAssistant


class Hub:
    """Dummy hub for Hello World example."""

    manufacturer = "Demonstration Corp"

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        """Init dummy hub."""
        self._host = host
        self._hass = hass
        self._name = host
        self._id = host.lower()
        self.online = True

    @property
    def hub_id(self) -> str:
        """ID for dummy hub."""
        return self._id

    async def test_connection(self) -> bool:
        """Test connectivity to the Dummy hub is OK."""
        await asyncio.sleep(1)
        return True
