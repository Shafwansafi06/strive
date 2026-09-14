# STRIVE SIH presentation runbook

## A. Before the event

Use Python 3.12 and install `requirements-demo.lock`. On this laptop keep Ubuntu
WSL available because Windows Application Control blocks the FAISS DLL. Connect the
laptop to power, close applications using port 8000, disable sleep, and use a
current browser. No internet is required after setup.

Run the final check:

```powershell
wsl -d Ubuntu -- bash -lc "cd /mnt/h/sih/STRIVE_MVP/strive-mvp && .venv-linux/bin/python scripts/presentation_check.py"
```

Expected final line: `READY FOR PRESENTATION`. Do not present if a mandatory item
fails. Optional licensed human samples can be imported using `data/demo/README.md`.

## B. One-command startup

```powershell
.\scripts\presentation.ps1
```

Open <http://127.0.0.1:8000>. The server is loopback-only. The screen must say
`DEMO EVIDENCE MODE — Not a neural accuracy benchmark`, backend healthy, model
`dsp-surrogate-v1`, and reference index ready.

## C–F. Recommended three-minute sequence

1. Click **Presentation Mode**. Say: “STRIVE monitors a call continuously. It does
   not wait for an upload verdict, and it does not claim identity from a low score.”
2. Leave the default ₹10,00,000, High urgency and New beneficiary context. Point to
   the three risk cards. Say: “Acoustic authenticity stays separate from business
   context. Only the policy layer combines them.”
3. Select **Presentation / realtime**, then **Mid-Call Voice Replacement**. Say:
   “This deterministic synthetic fixture guarantees the workflow; it is clearly
   labelled and is not a neural accuracy test.”
4. During 0–15 s, point to ANALYZING, then LOW OBSERVED RISK and the trusted in-call
   profile. Say: “There is no prior enrollment. STRIVE cautiously creates a
   temporary profile only after low artifact evidence and sufficient active audio.”
5. At the `VOICE CHANGE` marker, point to artifact, session and continuity tracks.
   Say: “A substantially different source now enters. Each branch reports its own
   availability and channel reliability.”
6. When policy reaches REVIEW/HIGH, point to the protected action. Click **Hold &
   Verify**. Say: “Detection alone is insufficient. STRIVE prevents the sensitive
   action while keeping the conversation open.”
7. Choose **Registered-number callback**, then **Failed**. Say: “Verification happens
   outside the potentially compromised voice channel. Failure blocks and escalates.”
   Reset and choose **Verified** if judges want the release path.
8. Open **Engineering status and latency** briefly. Point out actual geometry,
   current/p50/p95, queue and dropped windows. Say: “These are local runtime values,
   not claimed neural benchmark latency.”

## G. Evidence tracks

- Artifact / Spoof Evidence compares the current representation to the labelled
  reference index. Demo labels are procedural families.
- Session Voice Consistency measures distance from the trust-gated temporary
  in-call profile. Similarity and inconsistency are shown separately.
- Speech Continuity / Coherence is a supporting adjacent-segment change cue. It is
  unavailable without a valid voiced pair and is not a perfect splice detector.
- Channel Quality reports bandwidth, SNR proxy, clipping and input level. It changes
  reliability and never says that poor telephone audio is fake.

## H–I. Upload and prevention meaning

**Upload Call Audio** decodes in memory, converts to 16 kHz mono and replays frames
through the same call pipeline. Realtime mode represents a phone-call stream;
accelerated mode is for QA. An arbitrary upload has no ground-truth attack marker.

Hold/verify is a simulated integration seam. Callback, MFA and supervisor buttons
record audit metadata; they do not contact a bank or identity provider. Verified
may release the current action, failed blocks/escalates, and supervisor review stays
held. No raw speech enters the audit.

## J. Primary demo

Use Mid-Call Voice Replacement. Keep the synthetic label visible. The exact
threshold crossing is whatever the actual runtime events produce; never promise a
number before the run. If HIGH is not reached, demonstrate the context-driven REVIEW
and manually click Hold & Verify—do not alter thresholds during the presentation.

## K. Microphone demo

Click **Live microphone**, grant permission, and speak for at least six seconds.
Stop before changing devices. Explain that demo microphone scores are DSP surrogate
evidence. If permission is denied, use upload or the deterministic scenario.

## L. Offline fallback

Open `STRIVE_Demo.html` directly and select Mid-Call Voice Replacement. The page is
an offline replay of captured API events. It runs no model and cannot accept audio.

## M. Failure recovery

- Backend unavailable: close the server, rerun `presentation.ps1`, check port 8000.
- Windows FAISS block: use the WSL path selected by `presentation.ps1`.
- WebSocket disconnect: click Reset Demo and start a new call.
- Unsupported/corrupt/short/silent upload: choose a valid WAV/FLAC or install FFmpeg.
- Microphone denied: use scenario playback; change permission manually after the talk.
- Model/index missing in research mode: return to demo mode or prepare/seal assets;
  the system will not silently substitute a model.
- Total Python failure: use `STRIVE_Demo.html`.

## N. Known limitations

Default evidence is procedural DSP, not validated deepfake detection. NII/XLSR
weights and a real FAISS corpus are absent. No calibrated probability, Hindi/Hinglish
accuracy, real callback/MFA, SIP integration, browser-hardware mic automation, or
production authorization exists. Channel/prosody behavior needs licensed held-out
speech validation. Review `docs/VALIDATION.md` for actual measurements.

## O. Freeze commands

```bash
python -m pytest -q
node --check web/app.js
node --check web/pcm-worklet.js
node tests/audio_worklet.cjs
python scripts/build_demo.py
python scripts/presentation_check.py
python scripts/presentation_evidence.py
python scripts/stream_wav.py --scenario switch --mode accelerated --benchmark --hop 0.5
```
