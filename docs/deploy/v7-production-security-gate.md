# v7 Production Security Gate

This checklist blocks customer-batch release. Demo flashing on COM4 may proceed with the current HTTP/WebSocket and provisioning behavior, but a production release is not approved until every item below has implementation evidence and a recorded verification result.

## Release Blockers

- [ ] HTTPS/WSS is enforced and the device validates the server CA and hostname.
- [ ] Every device has a unique signed identity; shared fleet credentials are prohibited.
- [ ] Device requests and WebSocket controls have replay protection.
- [ ] Device and session tokens can be revoked without rebuilding firmware.
- [ ] OTA images are signed, signature verification is enforced, and Secure Boot is enabled.
- [ ] Flash Encryption and NVS Encryption are enabled with a documented key lifecycle.
- [ ] JTAG, USB-JTAG, UART download mode, and production log policy are explicitly locked down.
- [ ] Credential issuance, rotation, revocation, loss response, and factory reset are documented and tested.

## Required Evidence

For each blocker, attach the implementation commit, configuration snapshot, automated test result, and one hardware acceptance result. Secrets, complete device identifiers, tokens, SSIDs, and customer audio must not appear in the evidence.

## Decision

- Demo phase: permitted on explicitly authorized development devices and networks.
- Customer batch: blocked while any checkbox remains open.
