# Voice networking

The LiveKit Service exposes HTTP/WebSocket signaling on7880/TCP, RTC fallback on7881/TCP, and one UDP mux on50000/UDP. The pod declares those same listeners. A ClusterIP Service is reachable inside the local cluster; remote phones need a tailnet media path as well as HTTPS signaling.

`NODE_IP` is loaded from the non-secret `livekit-advertise` ConfigMap key `node_ip`. It sets the advertised RTC address through LiveKit1.13's supported environment variable. Resolve the host's current `tailscale ip -4` when preparing the deployment; validate that it is an IPv4 tailnet address, then create/update that ConfigMap. Do not commit a machine address or expect shell expressions inside the YAML to expand. A pod restart is required after the ConfigMap value changes.

`use_external_ip: false` preserves that explicit address. `advertise_internal_ip: true` retains the direct pod candidate for local clients alongside the mapped address. The existing API-key Secret is unchanged.

For remote clients, terminate WSS TLS with tailnet-only Tailscale Serve and forward raw TCP7881 to the LiveKit Service. Do not wrap the media TCP stream in HTTP, PROXY headers or another TLS layer. Both paths need a running local bridge. A foreground loopback proxy that resolves the stable Service address on startup has been tested with two synthetic browser clients; a kubectl port-forward media hop did not establish ICE in that test.

The single UDP port remains useful for direct local/cluster clients. Tailscale Serve TCP forwarding does not expose this UDP port. Verify the selected ICE candidate is the advertised tailnet TCP7881 address and that incoming/outgoing audio bytes increase; HTTP health alone is insufficient. Desktop browser emulation does not prove a physical phone.

Record exact started PIDs and Serve mappings for cleanup. Reuse existing healthy resources without taking ownership; stop only resources started by the current run. Keep credentials server-side and use qa-prefixed rooms for synthetic tests.

References: [LiveKit1.13.6 configuration](https://github.com/livekit/livekit/blob/v1.13.6/config-sample.yaml), [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).
