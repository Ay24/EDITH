# Edith Command Center

Edith is a Windows desktop assistant with voice control, Ollama-powered reasoning, media automation, system actions, persistent memory, and an immersive Jarvis-style UI.

## Features

- Multi-model local agent through Ollama
- Automatic Ollama startup and model pulling on launch
- F-drive Ollama model storage support through `OLLAMA_MODELS`
- Continuous voice listening with interrupt support
- YouTube and Spotify automation
- WhatsApp Desktop automation
- Windows controls for volume, brightness, Wi-Fi, updates, lock, and more
- Persistent memory and notes
- Animated UI with immersive mode and live speaking/listening states

## Project Layout

- `main.py`: launcher
- `edith_app/app.py`: app bootstrap
- `edith_app/assistant.py`: command routing and orchestration
- `edith_app/services/`: voice, audio, agent, knowledge, media, system, memory, and messaging services
- `edith_app/ui.py`: desktop interface and immersive mode

## Setup

1. Install Python 3.11 or newer.
2. Install the project:
   `pip install -e .`
3. Install Ollama on Windows.
4. Run Edith:
   `python main.py`

On startup, Edith now tries to:
- start Ollama automatically
- use `F:\OllamaModels` for model storage by default
- pull missing required models automatically when allowed

## Store Ollama Models on F Drive

Edith is configured to use:
- `F:\OllamaModels`

To make Ollama itself use that location consistently on Windows:
```bat
setx OLLAMA_MODELS F:\OllamaModels
```

Then fully close and reopen Ollama before starting Edith again.

## Environment Variables

- `OLLAMA_URL`
- `OLLAMA_MODELS`
- `OLLAMA_MODEL`
- `EDITH_PLANNER_MODEL`
- `EDITH_CREATIVE_MODEL`
- `EDITH_FAST_MODEL`
- `EDITH_WAKE_WORD`
- `EDITH_AUTO_LISTEN`
- `EDITH_REQUIRE_WAKE_WORD`
- `EDITH_LIGHTWEIGHT_MODE`
- `EDITH_AUTO_PULL_MODELS`

## Example Commands

- `system status`
- `open notebooklm`
- `play interstellar soundtrack on youtube`
- `spotify playlist deep focus`
- `message primary_contact saying this is a test message`
- `set volume to 40`
- `mute`
- `brainstorm a local-first AI product`
- `plan my study workflow`

## Notes

- Speech recognition currently uses the installed speech recognition pipeline.
- Online services like YouTube, Spotify, Google, Wikipedia, and WhatsApp sending still depend on their respective services being reachable.
- If Ollama is starting or a model is still being pulled, Edith will ask you to wait briefly and try again.
