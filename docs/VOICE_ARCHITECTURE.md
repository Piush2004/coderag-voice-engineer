# Voice Architecture

## What's real today

The frontend ([apps/frontend/app/page.tsx](../apps/frontend/app/page.tsx)) uses the
browser's native `SpeechRecognition` (STT) and `speechSynthesis` (TTS) Web APIs
directly, client-side. This is genuinely working — verified in-browser (push-to-talk
mic, live transcript, spoken answers) — with zero server involvement, zero API keys,
zero model downloads. It only works in browsers that implement these APIs (Chrome/
Edge reliably; Safari/Firefox support is partial/absent), and the frontend detects
support and falls back to text-only input when unavailable
(`voiceSupported` state in `page.tsx`).

## What's designed but not implemented

`SpeechToTextProvider` / `TextToSpeechProvider` interfaces exist in
[packages/shared/providers.py](../packages/shared/providers.py) so a server-side
implementation could be added without touching the agent or API layer. **No concrete
implementation exists.** This is a real gap, not a naming formality — see the
docstring on those classes for exactly why (no local model was pulled without a
concrete need beyond what the browser fallback already provides; no cloud STT/TTS
API key is available in this environment).

## What real server-side implementation would look like

- **Local**: `faster-whisper` (CTranslate2-based, meaningfully faster than
  openai-whisper on CPU) for STT — the `tiny`/`base` models (75MB/145MB) would be the
  right starting point per the "don't blindly download huge models" constraint, not
  `large`. No comparably good fully-local TTS exists that's small — Piper is the
  closest small/fast option if this is pursued.
- **Cloud**: Deepgram (streaming STT) and ElevenLabs (streaming TTS) are the
  interfaces this repo's env-var scaffolding
  ([.env.example](../.env.example)) already anticipates
  (`DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`) — wiring these in is mechanical once a
  key is available, following the same pattern as `AnthropicProvider`/
  `OllamaProvider` in `providers.py`.
- Either path would move transcription server-side, which matters for: consistent
  behavior across browsers, and giving the backend the audio stream directly for true
  full-duplex interruption handling (today, "stop talking" is handled entirely
  client-side via `window.speechSynthesis.cancel()` — real and working, but coarser
  than a server-mediated interrupt that could also cancel an in-flight agent run).

## Interruption — what's real

The Stop button and automatic pre-empt-on-new-input
(`stopSpeaking()` before starting a new recognition) in `page.tsx` are real and
tested in-browser. What's **not** implemented: cancelling an in-flight *agent run* on
the backend when the user interrupts mid-investigation — today a new `/chat` request
starts independently; the previous request's agent loop keeps running server-side
until it finishes or hits its own timeout/iteration limits (it doesn't affect the new
request, but it isn't actively cancelled either).
