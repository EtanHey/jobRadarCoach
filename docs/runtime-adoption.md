# Explicit voice lifecycle ownership

Adapters may declare `lifecycle_owned = True` when the application explicitly owns that service's lifecycle. The supervisor calls their idempotent `start(context)` even when the initial health probe succeeds, then records the returned identity as owned. An adapter must verify the approved resource before adopting it and capture sufficient identity for safe cleanup. After mutating a resource, startup failure must return its cleanup identity through `PartialStartError`.

Ctrl-C and startup rollback call `stop` only after the adapter verifies that recorded identity. All ordinary healthy services remain borrowed and are never stopped. This contract alone changes no concrete service ownership; LiveKit and Kokoro adapters are separate reviewed slices.
