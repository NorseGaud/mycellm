# mycellm Specification Evolution

## Phase 5: Quality-Aware Routing (March 2026)

### Problem
Heterogeneous models across the network have wildly different capability.
A 1B model and a 70B model both serve tokens, but quality is incomparable.
Consumers need guarantees about minimum intelligence for their requests.

### Solution: Quality Contracts

Requests can include quality constraints via the `mycellm` field in the
OpenAI-compatible chat completions body:

```json
{
  "model": "",
  "messages": [...],
  "mycellm": {
    "min_tier": "capable",
    "min_params": 8,
    "min_context": 16000,
    "required_tags": ["code"],
    "max_cost": 0.05,
    "routing": "best",
    "fallback": "reject"
  }
}
```

#### Tiers
- **frontier** (65B+): Rival GPT-4 class. 3x credit cost.
- **capable** (13B+): Production quality. 1.5x credit cost.
- **fast** (3B+): Good for simple tasks. 1x credit cost.
- **tiny** (<3B): Testing only. 0.5x credit cost.

#### Routing Modes
- **best**: Route to highest-scoring candidate (default)
- **fastest**: Send to top 3, return first response
- **ensemble**: Send to top 3, judge picks best (future)

#### Fallback
- **downgrade**: If no model meets constraints, use best available (with warning)
- **reject**: Return error if constraints can't be met

### Quality-Weighted Pricing
Models earn more credits for serving higher-tier inference:
| Tier | Multiplier | Incentive |
|------|-----------|-----------|
| frontier | 3.0x | Running 70B is profitable |
| capable | 1.5x | Mid-range rewarded |
| fast | 1.0x | Base rate |
| tiny | 0.5x | Low quality, low reward |

### Network Quality Floors
Each network can set `min_model_tier` to reject models below a threshold.
Public networks should require at least "fast" (3B+) to prevent noise.

### Model Features
ModelCapability now declares features: streaming, function_calling,
vision, json_mode. Routing can filter by required features.

### Future: Phase 6
- Request classification (auto-detect complexity -> route to appropriate tier)
- Quality verification (spot-check providers with eval prompts)
- Ensemble routing with judge model
- Capacity reservations and SLA guarantees
- Market-driven pricing (supply/demand auction)

---

## Phase 7: Protocol-Composable Workloads (Roadmap)

mycellm is the protocol layer — peer discovery, authenticated transport,
model-aware routing, and credit accounting. Like BitTorrent moves arbitrary
bits, mycellm can move arbitrary LLM workloads. The primitives are general;
only inference uses them today.

### Federated Fine-Tuning (LoRA)

Distributed adapter training without sharing raw data. Each node trains
locally, only small adapter weight deltas traverse the network.

**How it composes with existing primitives:**

| Training need | mycellm primitive |
|---|---|
| Find nodes with model X loaded | Model discovery (exists) |
| Send training data / adapter deltas | QUIC transport (exists) |
| Authenticate participants | Ed25519 identity (exists) |
| Track who contributed compute | Credit accounting (exists) |
| Coordinate training rounds | New message type over existing transport |

**Flow:**
1. A **training coordinator** (any node) advertises a fine-tuning job via
   the protocol — model, hyperparameters, round count, credit reward.
2. Participating seeders accept the job. Each performs local LoRA/QLoRA
   training on its own data.
3. After each round, nodes ship adapter weight deltas back to the
   coordinator over QUIC.
4. The coordinator aggregates deltas (e.g. FedAvg) and distributes the
   merged adapter for the next round.
5. Final adapter is published to the network as a shared artifact.

**Why it fits:** The coordinator ↔ seeder interaction is request/response,
same as inference. No tight gradient synchronization, no NCCL-style
collectives. Adapter deltas are small (MBs), well within QUIC throughput.

**New components needed:**
- `TrainingJob` message type in protocol envelope
- Training coordinator logic (job lifecycle, round management, aggregation)
- LoRA training harness wrapping llama.cpp or HuggingFace PEFT
- Adapter artifact registry (publish, discover, download adapters)

### P2P Model Distribution

Share GGUF model weights across the mesh — BitTorrent-style chunked
transfer over existing QUIC connections.

**How it composes:** Nodes already advertise which models they have via
model discovery. This adds the ability to *fetch* models from peers, not
just route inference to them. Chunked transfer with integrity verification
(SHA256 per chunk) over authenticated QUIC channels.

**New components needed:**
- Chunked file transfer protocol over QUIC streams
- Model registry with chunk manifests and integrity hashes
- Download coordination (parallel chunks from multiple peers)
- Storage quota management

### Distributed Eval Swarms

Farm out evaluation/benchmarking tasks across the network. This is
essentially inference with structured scoring — maps directly to existing
request routing.

**How it composes:** An eval job is a batch of inference requests with
expected outputs. The router distributes them across nodes. Results are
aggregated and scored centrally. Credit accounting tracks eval compute
contributions.

**New components needed:**
- Eval job definition format (prompt, expected output, scoring function)
- Batch request dispatcher (fan-out across peers)
- Score aggregation and reporting

### Mixture-of-Experts Routing

Route different requests (or parts of a request) to specialized
nodes/adapters based on content classification.

**How it composes:** The model resolver already selects models by tier,
tags, and features. MoE routing extends this with content-aware dispatch —
e.g., code questions to a code-tuned adapter, translation to a
multilingual model. Combined with federated fine-tuning, networks can
grow specialized expertise organically.

**New components needed:**
- Request classifier (lightweight model or heuristic)
- Adapter-aware routing in model resolver
- Adapter metadata in capability advertisements

### What Doesn't Compose

Some distributed ML workloads require fundamentally different transport
semantics and are **out of scope** for the mycellm protocol:

- **Distributed gradient descent** — requires all-reduce collectives with
  microsecond-level synchronization. Needs NCCL/Gloo, not request/response.
- **Model-parallel training** — splits a single model across nodes. Requires
  homogeneous hardware and datacenter-class interconnect bandwidth.
- **Pipeline parallelism** — similar bandwidth/latency constraints.

These workloads need their own protocol stack. mycellm's value is in
workloads that decompose into independent, asynchronous operations across
heterogeneous consumer hardware.
