# Device network service

`require('device_network')` provides asynchronous `scan()`, `connect(ssid, password)` and `status()`.
Only one operation can run; start methods return false when busy. Poll status().busy without blocking UI.
Status includes connected, ssid, ip, operation, generation, ok and networks (ssid, rssi, secured).
At most 24 AP records are returned. Passwords are never returned, logged, or written by this module.
Connect uses the same board provider as labplus_wifi.connect: save only after obtaining IP;
restore the previous saved configuration on failure. Connection timeout is 25 seconds.
Do not invoke connect automatically from generated programs; use the device settings UI.

Successful scan results are reused for 30 seconds when opening settings.
`scan(true)` explicitly refreshes, with a five-second cooldown after completion.
Cached success returns true without changing generation; clients keep the existing list.
