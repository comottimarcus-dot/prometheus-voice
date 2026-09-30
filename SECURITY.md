# Security and deployment boundaries

This is a local prototype. Keep the web application on loopback and do not expose its APIs through a public reverse proxy. Its local origin checks are not a substitute for internet authentication or a multi-user security model.

The optional Zhengchen bridge and OTA bootstrap support a trusted LAN demonstration. The OTA bootstrap can return the device credential to clients that can reach it. It is not a production firmware distribution or enrollment service. Restrict access to the intended device and do not expose it to the internet. The example configuration binds these optional services to loopback until the operator deliberately configures LAN access.

Never include credentials, private deployment addresses, raw audio, personal photographs or runtime ledgers in an issue or pull request. Keep `.env` mode 600. Rotate any credential accidentally disclosed outside the application.

Spoken camera confirmation is session-local and single-use. It checks a specific new user phrase after the permission question. It is not speaker identification or protection against all acoustic replay attacks.

A hash-linked local ledger is a consistency mechanism, not independent attestation. A user who controls the machine can replace an entire ledger. Telemetry freshness checks do not authenticate the physical node or its transport.

Report suspected issues privately to the repository owner through an available private GitHub channel. Do not publish exploitable details or secrets in a public issue.
