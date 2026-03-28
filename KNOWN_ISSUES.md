# mycellm — Known Issues

*Last updated: March 28, 2026 (v0.2.1)*

## Fixed in 0.2.1

### ~~QUIC framing bug broke all peer inference~~
Unidirectional QUIC streams were incorrectly parsed as iOS-style length-prefixed frames. Large inference responses arriving in multiple packets were silently dropped, causing "returned no result" on every gateway request. **Fixed**: framing only applies to bidirectional streams.

### ~~No P2P discovery between peers~~
Peers only knew about the bootstrap — not each other. LAN nodes behind the same NAT had no way to connect directly. **Fixed**: bootstrap now broadcasts peer exchange messages with addresses and capabilities. Peers auto-connect on LAN.

### ~~Gateway streaming was fake~~
The public gateway returned the full inference response as a single SSE chunk, even when `stream: true` was set. Users waited for the entire response before seeing any text. **Fixed**: true token-by-token streaming over QUIC — the gateway yields SSE chunks as they arrive from peers.

## Security & Privacy

### Prompts are visible to seeder nodes
When you send a message on the public network, the seeder node that runs inference sees your full prompt. This is inherent to the distributed architecture — the node needs the prompt to generate a response.

**Mitigation**: The [Sensitive Data Guard](https://docs.mycellm.dev/config/privacy-guard/) scans for API keys, passwords, and PII before sending. Use on-device inference for sensitive content.

### Credit system is not Sybil-resistant
New node identities receive 100 seed credits. An attacker could generate unlimited credits by creating new identities. Receipt validation is enforced locally — the bootstrap does not verify receipt signatures server-side.

**Impact**: Low for beta. Credits have no monetary value. Future: require proof-of-work or reputation-based credit issuance.

### No TLS certificate pinning on QUIC
Both iOS and Python disable TLS certificate verification on QUIC connections. Identity is verified at the application layer via Ed25519-signed NodeHello. A MitM attacker could observe (but not forge) authenticated traffic.

**Future**: Pin the bootstrap's public key or implement TLS channel binding with NodeHello.

## Infrastructure

### Single bootstrap node
The public network has one bootstrap server at `bootstrap.mycellm.dev`. If it goes down, new nodes cannot join and the public gateway is unavailable. Existing P2P connections on LAN continue working.

**Future**: Multiple bootstrap servers with DHT-based discovery fallback.

### Fleet management is partially implemented
Fleet commands `node.status`, `model.list`, and `model.scope` work. `model.load`, `model.unload`, and `set_mode` are not yet implemented on the iOS app.

### Multi-IP connection churn
When peer exchange shares all of a peer's LAN addresses, other nodes attempt connections to each address. Invalid addresses (wrong interfaces, Tailscale IPs) connect then idle-timeout, creating log noise. The peer_manager deduplicates by peer_id for new connections, but stale connections still churn.

**Future**: Address scoring — prefer addresses that previously succeeded.

## iOS App

### Foreground-only operation
iOS suspends apps after ~30 seconds in background. The QUIC connection drops, and the node goes offline. It reconnects when the app returns to foreground. For always-on nodes, use a Mac/Linux server.

### iOS does not stream inference from remote peers
The iOS app sends `stream: true` to the local node's OpenAI-compatible API, but when inference is routed to a remote peer over QUIC, the response arrives as a single blob. True token-by-token streaming over QUIC works on the Python gateway but is not yet wired in the iOS QUIC client.

### TLSConfig stub
`generateSelfSignedIdentity()` returns nil — the QUIC client TLS identity is not set. Transport encryption still works (aioquic generates ephemeral certs), but there's no persistent client certificate.

### Model sharding not implemented
The About page mentions model sharding across GPUs. This is a roadmap item — currently one model per node, loaded entirely into memory.

## Protocol

### DHT discovery is optional
The Kademlia DHT is not tested at scale. Use `--no-dht` if you experience issues. The bootstrap peer exchange is the primary discovery mechanism for connecting peers.

### Hole punching not wired end-to-end
STUN NAT discovery and hole punch primitives are implemented, but the bootstrap does not coordinate hole punch signaling between peers. Symmetric NAT (common on home routers) cannot be traversed. Peers behind the same NAT discover each other via peer exchange and connect directly on LAN.

**Workaround**: Peers always maintain an outbound QUIC connection to the bootstrap. The bootstrap uses this bidirectional connection to relay inference requests — no inbound port required.
