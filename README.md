<<<<<<< HEAD
# EDITH
A complete local system assitant exactly like edith and jarvis which will make you feel Like you are talking to your system 
=======
﻿# Edith Command Center

Edith is a polished desktop assistant project with a modular architecture, multi-model local open-source agent support, better media automations, NLP hooks, voice capture, and Windows-style utility actions.

## Free Open-Source Agent Path

This version no longer depends on OpenAI.

It uses a free local-agent route through Ollama. Recommended local models:
- `llama3.2`
- `mistral`
- `phi3`
- `qwen2.5`

Recommended multi-model role mapping:
- main chat: `llama3.2`
- planner: `qwen2.5`
- creative: `mistral`
- fast tactical: `phi3`

Set these optional environment variables if you want to customize the backend:
- `OLLAMA_URL`
- `OLLAMA_MODEL`
- `EDITH_PLANNER_MODEL`
- `EDITH_CREATIVE_MODEL`
- `EDITH_FAST_MODEL`
- `SPOTIFY_APP_PATH`
- `EDITH_NOTES_PATH`
- `EDITH_WAKE_WORD`
- `EDITH_AUTO_LISTEN`
- `EDITH_REQUIRE_WAKE_WORD`
- `EDITH_LIGHTWEIGHT_MODE`
- `EDITH_AUTO_PULL_MODELS`

## Features

- Local LLM-backed conversational agent through Ollama
- Multi-model brainstorming, planning, and paired-thinking flows
- spaCy-powered entity extraction hooks
- Speech recognition and text-to-speech support
- Continuous listening mode that can run until you manually stop it
- YouTube automation for direct play, home, and mix launching
- Spotify automation for launch, deep-link search, and playlist vibe flows
- Windows-like utility actions for Calculator, Notepad, Explorer, Settings, date, and time
- Broader system control hooks for brightness, Wi-Fi, updates, lock, sleep, and app launching
- File and folder search across common user directories
- Timestamped note capture
- Status dashboard and quick-action desktop interface

## Project Layout

- `main.py`: launcher
- `edith_app/app.py`: bootstrap
- `edith_app/assistant.py`: command orchestration
- `edith_app/services/`: agent, audio, knowledge, media, notes, and voice services
- `edith_app/ui.py`: desktop command center

## Setup

1. Install Python 3.11 or newer.
2. Create a fresh virtual environment.
3. Install the packages from `requirements.txt`.
4. Optionally install the spaCy English model:
   `python -m spacy download en_core_web_sm`
5. Install Ollama once so the `ollama` command exists on Windows.
6. Run the app:
   `python main.py`

At startup Edith now tries to start Ollama automatically.
Voice mode now starts automatically by default and listens continuously unless you stop it.
By default Edith accepts direct spoken commands even without the wake word.

For lower-end systems, Edith now defaults to a lighter setup:
- `phi3` is the default main model
- lightweight mode is on by default
- automatic model pulling is off by default
- the heavy spaCy model is skipped unless you disable lightweight mode

## Example Commands

- `open youtube`
- `youtube mix for synthwave coding`
- `play interstellar soundtrack on youtube`
- `open spotify`
- `spotify search lofi jazz`
- `spotify playlist deep focus`
- `brainstorm how to automate my workflow`
- `plan a daily automation workflow`
- `think with me about building a personal AI system`
- `find file invoice`
- `open folder %USERPROFILE%\\Documents`
- `set brightness to 60`
- `wifi on`
- `check updates`
- `update apps`
- `lock pc`
- `open calculator`
- `open notepad`
- `open settings`
- `search google for best windows automation tools`
- `save note polish the UI tonight`
- `system status`
>>>>>>> 68bfa2b (Updating on EDITH APP)
