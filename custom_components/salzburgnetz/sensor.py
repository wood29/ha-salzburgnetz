"""Status sensors for Salzburg Netz.

These only describe the import. The energy data itself goes into long-term
statistics, which the Energy dashboard reads directly.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SalzburgNetzConfigEntry
from .const import DOMAIN, SIGNAL_UPDATED
from .sync import KINDS, SalzburgNetzSync, statistic_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SalzburgNetzConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    sync = entry.runtime_data
    async_add_entities(
        [LastFullDaySensor(sync), DataUntilSensor(sync), StatusSensor(sync)]
    )


class _Base(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, sync: SalzburgNetzSync, key: str) -> None:
        self.sync = sync
        self._attr_unique_id = f"{sync.zp}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sync.zp)},
            name=sync.entry.title,
            manufacturer="Salzburg Netz",
            model="Smart meter (service portal API)",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATED.format(self.sync.entry.entry_id),
                self._updated,
            )
        )

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()


class LastFullDaySensor(_Base):
    """kWh of the most recent complete day (no state_class: no duplicate statistics)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, sync: SalzburgNetzSync) -> None:
        super().__init__(sync, "last_full_day")

    @property
    def native_value(self):
        day = self.sync.last_full_day()
        return day[1] if day else None

    @property
    def extra_state_attributes(self):
        day = self.sync.last_full_day()
        return {"date": day[0].isoformat()} if day else None


class DataUntilSensor(_Base):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, sync: SalzburgNetzSync) -> None:
        super().__init__(sync, "data_until")

    @property
    def native_value(self):
        return self.sync.data_until()


class StatusSensor(_Base):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, sync: SalzburgNetzSync) -> None:
        super().__init__(sync, "status")

    @property
    def native_value(self):
        return self.sync.status[:255]

    @property
    def extra_state_attributes(self):
        history = self.sync.history_from()
        state = self.sync.state
        return {
            "history_from": history.isoformat() if history else None,
            "history_complete": bool(state.get("backfill_done")),
            "last_sync": state.get("last_sync"),
            "statistic_ids": [
                statistic_id(self.sync.zp, kind)
                for kind in KINDS
                if self.sync.hours[kind]
            ],
        }
