# Salzburg Netz Smart Meter for Home Assistant

This integration brings the 15-minute values from your Salzburg Netz smart meter into the Home Assistant **Energy dashboard**. It uses the official API of the Salzburg Netz service portal.

- Once a day at 11:40 it downloads the last 3 days. Salzburg Netz updates the data once a day, and it is mostly complete by 10–12h.
- It then fills in older history, one 90-day piece per day, back to the 3 years the API offers. Expect about 12 days until the history is complete.
- The 15-minute values are added up per hour, which is the level the Energy dashboard stores.
- It makes at most 2 requests a day, so it stays well inside the API's small daily limit. If Salzburg Netz still says "too many requests", it waits as long as the API asks and never retries in a loop.
- The data arrives a day late. For live power you need a reader on the meter's customer port.

## What you need

From the Salzburg Netz service portal:

1. **API key:** go to Kundenkonto (bottom left) → Mein Benutzerkonto → scroll to **API Schlüssel**. Enter a name (e.g. "Home Assistant St. Gilgen"), choose the validity (up to 2 years) → **Schlüssel erstellen** → copy it with the copy icon. You can make a separate key for Home Assistant, so it can be deleted on its own later.
2. **Customer number (GPNR):** 8 digits, starts with 1.
3. **Metering point (Zählpunkt):** 33 characters, starts with AT004000…

## Installation

### Option A: HACS (gets updates)

1. HACS → ⋮ (top right) → **Custom repositories**.
2. Repository: `https://github.com/wood29/ha-salzburgnetz`, Type: **Integration** → **Add**.
3. Search for **Salzburg Netz Smart Meter** → **Download**.
4. Settings → System → **Restart**.

### Option B: copy the folder

1. Copy the folder `custom_components/salzburgnetz` into the `custom_components` folder of your Home Assistant config. You can do this with the *Samba share* or *Studio Code Server* add-on. The result is `/config/custom_components/salzburgnetz/manifest.json` and so on. Create `custom_components` if it doesn't exist.
2. Settings → System → **Restart**.

## Setup

1. Settings → Devices & services → **Add integration** → search for **Salzburg Netz**.
2. Fill in the Name (e.g. "St. Gilgen"), API key, customer number and metering point → **Submit**.
3. Within a minute it downloads the last 90 days. Check the **St. Gilgen Sync status** sensor: it should say `ok`.

## Add it to the Energy dashboard

1. Settings → Dashboards → **Energy** (or the Energy dashboard → ⋮ → Energy configuration).
2. Under **Electricity grid** → **Add consumption** → choose **St. Gilgen consumption**. It is listed among the statistics, not as a normal sensor.
3. Optional: enter your price per kWh.
4. **Save**. Yesterday and earlier show up right away. Today stays empty until tomorrow after 11:40.

## Sensors it adds

| Sensor | Meaning |
|---|---|
| Last full day | kWh of the most recent complete day (date in the attributes) |
| Data until | Time of the newest value received |
| Sync status | `ok`, or what went wrong. The attributes show how far back the history goes and whether it is complete |

These sensors are only for information. The Energy dashboard reads the hourly statistics directly.

## When the key expires

Keys are valid for up to 2 years. When Salzburg Netz rejects the key, you get a notification and Sync status says *API key rejected*. Create a new key in the portal, then go to Settings → Devices & services → Salzburg Netz → ⋮ → **Reconfigure** and paste it. It downloads again within a minute.

## Notes

- Removing the integration also deletes its statistics.
- If you also feed electricity into the grid (OBIS 1-1:2.9.0), a second statistic **… feed-in** appears. You can add it under *Return to grid*.
- The daily limit applies to your Salzburg Netz account. If another program uses the same API, it shares that limit. That's why this integration runs at 11:40 and makes only 1–2 requests a day.
