# BMW CarData Home Assistant Integration

Hi Home Assistant community,

This project was driven as a successor of Bimmmerconnected and mainly inspired by https://github.com/dj0abr/bmw-mqtt-bridge.

My target is to create an integration which is easy to use and supports all reqiurements. The integration is vibe code because I have no time to code by myself.

## The integration supports follow:

- Simple configuration VIN+ClientID+GCID which all available in the CarStream menu at BMW or Mini Website
- Support of multiple vehicle with one account and multipe accounts with one vehicle (each vehicle creates its own device with multiple entities/sensor)
- No preconfiguration of any sensor in Home Assistant. The sensor will appear if configured in the CarStream and the vehicle is awake.





Direct Home Assistant integration for [BMW CarData](https://github.com/dj0abr/bmw-mqtt-bridge) streaming. **No MQTT broker required** – the integration connects to BMW's CarData MQTT stream and exposes vehicle data as sensors.

## Installation

1. Copy the `custom_components/bmw_cardata` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings** → **Devices & services** → **Add integration** and search for **BMW CarData**.

The integration includes a BMW roundel logo (in `brand/icon.png` and `brand/logo.png`). On **Home Assistant 2026.3+** the icon can be used automatically via the brands proxy. If you see **"icon not available"** on the integration card, add the brand to the official repo once (see below).

### If the integration icon does not show ("icon not available")

Home Assistant loads integration icons from its brands system. To make the BMW icon appear for all users and versions:

1. Run: `python custom_components/bmw_cardata/brand/prepare_brands_pr.py` (creates `brand_for_ha_brands/bmw_cardata/` with the PNGs).
2. Fork [home-assistant/brands](https://github.com/home-assistant/brands) and create folder `custom_integrations/bmw_cardata/`.
3. Add `icon.png` and `logo.png` from the prepared folder into that path in your fork.
4. Open a Pull Request to `home-assistant/brands`. After it is merged, the icon will appear in Settings → Integrations (and in the add-integration dialog).

## Setup (onboarding)

1. **Client ID**  
   In the My BMW app or website: **Personal Data** → **My Vehicles** → **CarData** → **Create Client ID**. Copy the GUID (e.g. `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

2. **GCID**  
   Same place: **CARDATA STREAM** → **Show Connection Details** → copy the **USERNAME** value (this is your GCID).

3. Enter both values in the integration form and submit.

4. **Complete login**  
   Open the URL shown in the next step in your browser, sign in with your BMW account, and approve access. When you see "Anmeldung erfolgreich" or "Login successful", return to Home Assistant and click **Submit**.

After setup, the integration will:

- Connect to BMW's CarData stream (no local Mosquitto needed).
- Refresh tokens automatically.
- Expose a **connection** binary sensor and **dynamic sensors** for each data signal (fuel, range, location, etc.) as they are streamed by your vehicle.

**When will entities show data?** The BMW CarData stream is push-only – BMW sends data when the vehicle reports. Entities stay "unknown" until your vehicle has reported data. This typically happens when:
- The vehicle was recently driven or used
- The My BMW app was opened recently (which can wake the vehicle)
- The vehicle is awake and connected to BMW's backend

**Service `bmw_cardata.request_refresh`** – Reconnects to the BMW CarData stream. May help in some edge cases (e.g. stale connection). Data flow is driven by BMW, not by reconnecting.

## Entities

- **Binary sensor**: CarData stream connection status (on/off).
- **Device tracker**: Vehicle position (latitude/longitude) shown on the map. Appears on the Map card when BMW reports location data.
- **Sensors**: One sensor per CarData signal per vehicle (e.g. fuel percentage, range, latitude, longitude). New signals appear as they are received from BMW.

## Known issues:

- Missing Icon/Logo
- The VIN sensor sometime switches between the actual VIN and the VIN does not match.

## Credits

Based on the [bmw-mqtt-bridge](https://github.com/dj0abr/bmw-mqtt-bridge) project (OAuth2 device flow and BMW CarData MQTT protocol).
