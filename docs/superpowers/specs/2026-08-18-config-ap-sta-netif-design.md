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

The existing `WifiStation` ownership remains unchanged. `WifiManager` will add
a dedicated transition mutex that covers each complete mode transition,
including the underlying Stop and Start calls. This prevents another task from
creating a default `WIFI_STA_DEF` while the previous owner is still tearing it
down. State inspection continues to use the existing state mutex. Application
event callbacks run only after the transition mutex is released so callback
re-entry cannot deadlock the transition path.

`WifiConfigurationAp` will also make asynchronous work session-aware:

- A stopping flag prevents scans and new credential validation after shutdown
  begins.
- Stopping sets the connection failure/cancellation event bit so an in-flight
  `/submit` request does not wait for the full DHCP timeout.
- `is_connecting_` is atomic because it is shared by the HTTP and timer/event
  tasks.
- Delayed exit work carries a configuration-session generation. `Stop()`
  invalidates the generation, so an exit scheduled by an old session cannot
  stop a newly started session.

## Data flow

1. `WifiManager::StartConfigAp()` acquires the transition mutex and stops the
   active station, including its STA netif.
2. `WifiConfigurationAp::Start()` starts a new configuration generation.
3. `WifiConfigurationAp::StartAccessPoint()` creates temporary STA and AP
   netifs, selects APSTA mode, and starts Wi-Fi.
4. `/submit` calls `ConnectToWifi()`. The STA netif provides DHCP and emits
   `IP_EVENT_STA_GOT_IP` on success.
5. The credentials are saved and a generation-bound exit is scheduled.
6. `WifiConfigurationAp::Stop()` invalidates the generation, wakes any
   connection waiter, quiets HTTP/event/timer work, stops Wi-Fi, and destroys
   both temporary netifs.
7. The Manager releases the transition mutex and emits the ConfigModeExit
   event.
8. The normal station transition creates its own STA netif and reconnects
   using the saved credentials.

## Shutdown order

Configuration mode shutdown follows this order:

1. Atomically mark the session as stopping and invalidate delayed exits.
2. Prevent new scans and set `WIFI_FAIL_BIT` to wake `ConnectToWifi()`.
3. Stop the scan timer so it cannot initiate new scans.
4. Stop the HTTP server after the connection waiter has been released.
5. Unregister SmartConfig, Wi-Fi, and IP event handlers. Event handlers check
   the stopping flag before touching the timer or connection state.
6. Delete the stopped scan timer.
7. Stop Wi-Fi.
8. Destroy the temporary STA netif and AP netif and clear both pointers.
9. Clear transient connection state for the next generation.

## Error handling

The change preserves the component's current fail-fast initialization policy:
ESP-IDF's default netif creation helpers assert on creation or attachment
failure. Each owned pointer is destroyed at most once during a transition and
is cleared immediately afterward. The transition mutex, stopping flag, and
generation checks provide the concurrency guarantees; pointer null checks
alone are not treated as thread safety.

## Verification

- Add regression checks for temporary STA ownership, creation, shutdown order,
  and destruction.
- Add host-testable transition/generation policy coverage for repeated
  `Station -> Config -> Station` cycles, concurrent transition attempts, and
  stale delayed exits after immediate re-entry.
- Verify a failed credential attempt leaves the configuration AP available for
  another submission.
- Run the focused regression tests and existing Python tests.
- Build the ESP32-S3 firmware with ESP-IDF v5.5.4.
- Hardware acceptance requires deleting a saved network, submitting it again,
  and observing `IP_EVENT_STA_GOT_IP` before the portal timeout. This step is
  performed only after explicit authorization for serial or OTA operations.

## Exclusions

This change does not modify credential storage, Wi-Fi passwords, scan policy,
OTA release state, server deployment, partition contents, or serial flashing.
