# STRIVE HTTP and streaming API

Base URL: `http://127.0.0.1:8000`. OpenAPI is at `/docs`. All scores use 0–1; the dashboard displays 0–100. The score is not calibrated. Both `calibrated` and `demo_only` are explicit in each event.

Loopback development allows an empty token. Set `STRIVE_API_TOKEN` for bearer authentication; the launcher requires it when binding beyond loopback. Use HTTPS for network deployments. This shared token is a prototype control, not tenant isolation or organization IAM.

| Method / route | Contract |
|---|---|
| `GET /health` | Unauthenticated process health; mode and version |
| `GET /ready` | Initialized model/index status and validation flags |
| `GET /metrics` | Window count, errors, latency sum, active calls, stride overruns |
| `GET /v1/config` | Public settings and model version, excluding token and local paths |
| `POST /v1/calls` | JSON `language` plus optional `context`; returns opaque UUID and stream path |
| `POST /v1/calls/{id}/chunks` | JSON `sequence` and base64 `pcm_s16le`; returns zero or more window events |
| `WS /v1/stream/{id}` | Authenticate in first message; then same PCM frame contract |
| `PATCH /v1/calls/{id}/context` | Replace business context; invalidates prior mock verification |
| `POST /v1/calls/{id}/transaction` | Attempt a mock transfer; returns `held_mock` or `executed_mock` |
| `POST /v1/calls/{id}/verify` | Record external verification; requires method and explicit confirmation |
| `GET /v1/calls/{id}/audit` | Up to 1,000 score/action audit records |
| `DELETE /v1/calls/{id}` | End call and discard transient raw audio/profile state |
| `POST /v1/analyze?language=hi` | Raw encoded-audio request body, up to 20 MiB / 120 seconds; memory-only decoding |
| `POST /v1/demo/{scenario}` | Demo-only procedural-audio run; fixture results cannot activate research mode |

Call creation example:

```json
{
  "language": "hi",
  "context": {
    "amount_inr": 4000000,
    "urgent": true,
    "new_beneficiary": false,
    "privileged_request": false
  }
}
```

Language values: `auto`, `und`, `hi`, `ta`, `te`, `bn`, `mr`, `kn`, `en`, `mixed`. These tags configure routing; their presence is not evidence of tested language coverage. Operator hints are recorded as hints. Automatic language inference runs once after initial audio when its local model is installed; otherwise route unknown/global.

## WebSocket protocol

1. Create a call over HTTP. Connect to its returned `ws_path` on the same origin.
2. Send `{"token":"YOUR_TOKEN"}` or `{"token":""}` for local development. Credentials never appear in the URL.
3. Wait for `{"type":"ready","sample_rate":16000}`.
4. Send frames with sequence 0,1,2,…, encoded signed 16-bit little-endian **16 kHz mono PCM**. Maximum frame: 2 seconds; browser sends 1 second. Arbitrary shorter frames are allowed.
5. Wait for each `type:events` acknowledgement. An acknowledgement can contain no events until a full window is present. Results have explicit audio timestamps.
6. On a known dropped-audio gap, send `{"type":"gap"}`. It discards the profile and returns to uncertainty. The expected sequence remains unchanged. Out-of-order or duplicate frames are rejected.
7. Closing the authenticated socket ends its call. The server also reaps idle sessions; the UI should start a new call after expiry.

The browser bounds its queue and stops capture if the engine cannot keep up. The server limits active calls, input frame size and maximum audio duration. It is a single-process prototype, not a throughput claim.

## Score semantics

- `s_global`: fraction of spoof-labelled nearest neighbors; demo labels mean procedural signal family.
- `session_similarity`: normalized similarity to existing accepted profile entries.
- `s_session`: `1 - session_similarity`, clipped to [0,1]. Missing profile returns null.
- `s_coherence`: clipped adjacent-segment cosine discontinuity near the overlapping window seam.
- `weights`: age-scheduled weights after availability masking.
- `s_risk` / `authenticity_risk`: acoustic EMA, or null for insufficient current evidence.
- `context_risk`: independent heuristic based on supplied transaction metadata.
- `decision_risk`: `1 - (1 - acoustic_risk) * (1 - 0.5 * context_risk)`; null if acoustic evidence is unavailable.

## Channel state (CH-07)

Every risk event carries a `channel` object describing the **transport**, never the
speaker. A degraded channel means the acoustic evidence deserves less trust; it is not
itself evidence of a clone. Values that could not be measured are `null`, never `0`.

```json
"channel": {
  "sample_rate": 16000,
  "estimated_bandwidth_hz": 7600.0,
  "snr_db": 18.2,
  "clipping_ratio": 0.001,
  "rms_dbfs": -21.4,
  "discontinuity_score": 0.12,
  "packet_loss_rate": null,
  "jitter_ms": null,
  "codec": null,
  "quality": 0.84
}
```

| Field | Meaning |
|---|---|
| `estimated_bandwidth_hz` | Occupied-bandwidth estimate: 99% cumulative-power rolloff on the averaged 512-point STFT. Separates narrowband from wideband. Content-dependent; `null` below the silence floor. |
| `snr_db` | Rough SNR **proxy**, clamped to [0, 60]. Minimum-statistics noise floor (10th percentile of each frequency bin across time) against total power. Monotonic in added noise but biased high; not a laboratory measurement. |
| `clipping_ratio` | Fraction of samples at or beyond ±0.99. |
| `rms_dbfs` | Window level; `null` on digital silence. |
| `discontinuity_score` | Bounded [0,1] continuity signal across adjacent windows: max of energy, noise-floor, spectral-centroid and boundary-step jumps. The first window has no predecessor and scores `0`. |
| `packet_loss_rate`, `jitter_ms`, `codec` | Transport metadata supplied by the caller; `null` when the transport does not report it. |
| `quality` | Conservative **reliability** scalar in [0,1]. It is *not* a spoof probability. `null` when no usable audio was present. Individual features remain available regardless. |

Every event also carries `capture` (AUD-04 queue counters), `scheduler` (SCH-03
cadence telemetry) and `dropped_windows`. See `docs/LATENCY.md`.

Backward compatibility: `channel` is additive. `schema_version` is now `"1.1"` because `latency_ms`
changed from a float to `{compute, queue, end_to_end}`; every other addition is
additive and clients that ignore unknown keys are unaffected. Per-stage timings are in `stage_ms`, which now
includes `channel` alongside `features` and `tracks`.

Window geometry is configurable (`window_s`, `stride_s`, both exposed by `/v1/config`).
`stride_s` must satisfy `0 < stride_s <= window_s` and land on whole 16 kHz samples.
2 s/1 s, 2 s/0.5 s and 4 s/0.5 s are covered by tests. Event rate follows the hop, so a
0.5 s stride emits roughly two events per second after warm-up.

Context thresholding can hold a sensitive action while acoustic risk remains unknown. The mock transaction endpoint also holds stale/uncertain evidence and latches prior alerts. Demo-mode transactions always require a mock verification. Verification applies only to the current received sequence; subsequent evidence or context changes can invalidate it.

## Privacy and limits

Raw request audio and in-call vectors are transient; uploads do not use multipart temporary files. SQLite stores an explicit whitelist of timestamps, UUID call IDs, scores, reasons, actions and model/version metadata. It does not store PCM, phoneme/profile vectors or pitch measurements. Local audit is retained for seven days with cleanup on startup. It is not encrypted at rest by this MVP.

The upload endpoint closes its session after processing; it cannot subsequently execute a transaction. A final incomplete window is not zero-padded into new evidence. Its unscored sample count is reported. Browser/device privacy still depends on the local OS and hosting controls.
