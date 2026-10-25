import custom_components.salzburgnetz.sync  # noqa
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.util import dt as dt_util

TZ = ZoneInfo("Europe/Vienna")

async def test_cost_import(recorder_mock, enable_custom_integrations, hass, hass_storage):
    await hass.config.async_update(currency="EUR", time_zone="Europe/Vienna")
    today = dt_util.now(TZ).date()
    sep1 = datetime(2026, 9, 1, tzinfo=TZ).timestamp()
    hours = {str(int(sep1 - 3600)): 1.0, str(int(sep1)): 2.0, str(int(sep1 + 3600)): 0.5}
    entry = MockConfigEntry(domain="salzburgnetz", title="St. Gilgen", unique_id="AT0040000000000000000000002197186",
        data={"api_key": "x"*20, "gpnr": "12345678", "zp": "AT0040000000000000000000002197186"},
        options={"price_entity": "sensor.price"})
    entry.add_to_hass(hass)
    hass_storage[f"salzburgnetz.{entry.entry_id}"] = {"version": 1, "key": f"salzburgnetz.{entry.entry_id}",
        "data": {"hours": {"consumption": hours}, "state": {"last_sync": today.isoformat()}}}
    hass.states.async_set("sensor.price", "0.4176", {"valid_from": "2026-09-01", "unit_of_measurement": "EUR/kWh"})
    calls = []
    with patch("custom_components.salzburgnetz.sync.async_add_external_statistics", side_effect=lambda h, m, r: calls.append((m, r))):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        cost = [c for c in calls if c[0]["statistic_id"] == "salzburgnetz:cost_2197186"]
        assert cost, calls
        meta, rows = cost[-1]
        assert meta["unit_of_measurement"] == "EUR"
        assert [round(r["state"], 4) for r in rows] == [0.8352, 0.2088]
        assert round(rows[-1]["sum"], 4) == 1.044
        # price change applies from its valid_from, costs rewritten from there
        calls.clear()
        hass.states.async_set("sensor.price", "0.5", {"valid_from": "2026-09-01T01:00:00", "unit_of_measurement": "EUR/kWh"})
        await hass.async_block_till_done()
        cost = [c for c in calls if c[0]["statistic_id"] == "salzburgnetz:cost_2197186"]
        meta, rows = cost[-1]
        assert len(rows) == 1 and round(rows[0]["state"], 4) == 0.25 and round(rows[0]["sum"], 4) == 1.0852
        # unavailable keeps prices
        calls.clear()
        hass.states.async_set("sensor.price", "unavailable")
        await hass.async_block_till_done()
        assert not calls
        # options flow
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form"
    await hass.config_entries.async_unload(entry.entry_id)
