"""Salzburg Netz smart meter: 15-minute load profile into the Energy dashboard."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .sync import SalzburgNetzSync

PLATFORMS = [Platform.SENSOR]

type SalzburgNetzConfigEntry = ConfigEntry[SalzburgNetzSync]


async def async_setup_entry(hass: HomeAssistant, entry: SalzburgNetzConfigEntry) -> bool:
    sync = SalzburgNetzSync(hass, entry)
    await sync.async_start()
    entry.runtime_data = sync
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SalzburgNetzConfigEntry) -> bool:
    entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: SalzburgNetzConfigEntry) -> None:
    await SalzburgNetzSync(hass, entry).async_remove()
