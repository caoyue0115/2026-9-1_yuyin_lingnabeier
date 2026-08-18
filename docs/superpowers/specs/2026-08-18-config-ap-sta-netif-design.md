# Config AP STA netif lifecycle fix

## Problem

After a device has connected to Wi-Fi, entering configuration mode stops
`WifiStation`. Its shutdown path destroys the default STA netif. The
configuration portal then starts Wi-Fi in `WIFI_MODE_APSTA`, but creates only
the AP netif. Credential validation can therefore associate with the selected
access point without a DHCP client and never receives `IP_EVENT_STA_GOT_IP`.

This appears when a saved network is deleted and the same network is submitted
again: the portal waits for an IP address, times out, and reports a connection
failure even though the password and radio link are valid.

## Design

`WifiConfigurationAp` will own both default netifs required by its APSTA mode:

- Create a default STA netif and a default AP netif before starting Wi-Fi.
- Keep both netifs alive while the captive portal validates credentials.
- Stop Wi-Fi before destroying either netif.
- Destroy both netifs and clear their pointers when configuration mode stops.

The existing `WifiStation` ownership remains unchanged. `WifiManager` already
serializes mode transitions: it fully stops Station before starting Config AP,
and fully stops Config AP before starting Station. That prevents duplicate
default STA netifs.

## Data flow

1. `WifiManager::StartConfigAp()` stops the active station, including its STA
   netif.
2. `WifiConfigurationAp::StartAccessPoint()` creates temporary STA and AP
   netifs, selects APSTA mode, and starts Wi-Fi.
3. `/submit` calls `ConnectToWifi()`. The STA netif provides DHCP and emits
   `IP_EVENT_STA_GOT_IP` on success.
4. The credentials are saved and configuration mode exits.
5. `WifiConfigurationAp::Stop()` stops Wi-Fi and destroys both temporary
   netifs.
6. The normal station mode creates its own STA netif and reconnects using the
   saved credentials.

## Error handling

The change preserves the component's current fail-fast initialization policy:
ESP-IDF's default netif creation helpers assert on creation or attachment
failure. Teardown remains null-safe and idempotent for each owned pointer.

## Verification

- Add a regression test that verifies Config AP owns a STA netif, creates it
  for APSTA operation, and destroys it during teardown.
- Run the focused regression test and existing Python tests.
- Build the ESP32-S3 firmware with ESP-IDF v5.5.4.
- Hardware confirmation remains a separate step: delete a saved network,
  submit it again, and verify `IP_EVENT_STA_GOT_IP` arrives before the portal
  timeout.

## Exclusions

This change does not modify credential storage, Wi-Fi passwords, scan policy,
OTA release state, server deployment, partition contents, or serial flashing.
