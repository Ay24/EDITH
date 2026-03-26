from __future__ import annotations

import re
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime

from edith_app.config import AppConfig
from edith_app.models import AssistantSnapshot, ChatMessage, CommandResult
from edith_app.services.agent_service import AgentService
from edith_app.services.audio_service import AudioService
from edith_app.services.knowledge_service import KnowledgeService
from edith_app.services.media_service import MediaService
from edith_app.services.notes_service import NotesService
from edith_app.services.system_service import SystemService
from edith_app.services.voice_service import VoiceService

try:
    import phonenumbers
except ImportError:
    phonenumbers = None


class EdithAssistant:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.history: list[ChatMessage] = []
        self.agent = AgentService(config)
        self.audio = AudioService()
        self.voice = VoiceService()
        self.knowledge = KnowledgeService(
            user_agent=f"{config.persona.name}/3.0 desktop assistant",
            lightweight_mode=config.lightweight_mode,
        )
        self.media = MediaService(config)
        self.notes = NotesService(config.notes_path)
        self.system = SystemService()

    def snapshot(self) -> AssistantSnapshot:
        return AssistantSnapshot(
            mode="Local Agent Command Center",
            ai_enabled=self.agent.enabled,
            voice_enabled=self.voice.enabled,
            audio_enabled=self.audio.system_audio_enabled,
        )

    def greet(self) -> str:
        greeting = (
            f"{self.config.persona.name} online. Local agent, voice controls, media automations, "
            "and desktop routines are ready."
        )
        self._remember("assistant", greeting)
        return greeting

    def speak(self, text: str) -> None:
        self.audio.speak(text)

    def listen_once(self) -> str:
        return self.voice.listen_once()

    def listen_for_command(self) -> str:
        return self.voice.listen_for_command(timeout=self.config.voice_command_timeout)

    def handle(self, command: str) -> CommandResult:
        command = command.strip()
        lowered = command.lower()
        self._remember("user", command)

        if not command:
            result = CommandResult("I need a command to work with.")
        elif lowered in {"help", "capabilities", "what can you do"}:
            result = CommandResult(self._capabilities(), action="help")
        elif lowered.startswith("open youtube"):
            result = CommandResult(self.media.open_youtube_home(), action="youtube")
        elif "youtube mix" in lowered:
            query = self._strip_words(lowered, ["youtube mix", "for"])
            result = CommandResult(self.media.launch_youtube_mix(query or "focus music"), action="youtube")
        elif "play" in lowered and "on youtube" in lowered:
            query = lowered.replace("play", "", 1).replace("on youtube", "", 1).strip()
            result = CommandResult(self.media.search_youtube(query or "music"), action="youtube")
        elif lowered.startswith("open spotify"):
            result = CommandResult(self.media.open_spotify(), action="spotify")
        elif lowered.startswith("spotify search"):
            query = self._strip_words(lowered, ["spotify search"])
            result = CommandResult(self.media.search_spotify(query or "cinematic soundtrack"), action="spotify")
        elif lowered.startswith("spotify playlist"):
            vibe = self._strip_words(lowered, ["spotify playlist", "for"])
            result = CommandResult(self.media.playlist_for_vibe(vibe or "deep focus"), action="spotify")
        elif lowered.startswith("search google for"):
            query = self._strip_words(lowered, ["search google for"])
            result = CommandResult(self._google(query), action="browser")
        elif lowered in {"open google", "google"}:
            result = CommandResult(self._google(""), action="browser")
        elif lowered.startswith("open github"):
            result = CommandResult(self.media.open_site("https://github.com/", "GitHub"), action="browser")
        elif lowered.startswith("open stackoverflow"):
            result = CommandResult(self.media.open_site("https://stackoverflow.com/", "Stack Overflow"), action="browser")
        elif lowered.startswith("open gmail"):
            result = CommandResult(self.media.open_site("https://mail.google.com/", "Gmail"), action="browser")
        elif lowered.startswith("open whatsapp"):
            result = CommandResult(self.system.open_website("https://web.whatsapp.com/", "WhatsApp"), action="browser")
        elif lowered.startswith("open folder "):
            target = command[len("open folder "):].strip()
            result = CommandResult(self.system.open_folder(target), action="files")
        elif lowered.startswith("find file ") or lowered.startswith("find folder "):
            query = command.split(" ", 2)[2].strip()
            result = CommandResult(self._search_files(query), action="files")
        elif lowered.startswith("open calculator"):
            result = CommandResult(self.system.open_app("calculator"), action="system")
        elif lowered.startswith("open notepad"):
            result = CommandResult(self.system.open_app("notepad"), action="system")
        elif lowered.startswith("open settings"):
            result = CommandResult(self.system.open_app("settings"), action="system")
        elif lowered.startswith("open explorer") or lowered.startswith("open files"):
            result = CommandResult(self.system.open_app("explorer"), action="system")
        elif lowered.startswith("open ") and len(lowered.split()) >= 2:
            app_name = command[len("open "):].strip()
            result = CommandResult(self.system.open_app(app_name), action="system")
        elif lowered in {"time", "what is the time", "the time"}:
            result = CommandResult(f"The time is {datetime.now().strftime('%I:%M %p') }.", action="clock")
        elif lowered in {"date", "what is the date", "today's date", "todays date"}:
            result = CommandResult(f"Today's date is {datetime.now().strftime('%A, %d %B %Y')}.", action="clock")
        elif "wikipedia" in lowered:
            topic = lowered.replace("wikipedia", "", 1).strip() or "artificial intelligence"
            result = CommandResult(self.knowledge.summarize_topic(topic), action="knowledge")
        elif lowered.startswith("save note") or "take note" in lowered or "note this" in lowered:
            note = self._extract_note(command)
            result = CommandResult(self.notes.save(note), action="note")
        elif lowered.startswith("increase volume"):
            result = CommandResult(self.audio.adjust_volume(0.1), action="audio")
        elif lowered.startswith("decrease volume"):
            result = CommandResult(self.audio.adjust_volume(-0.1), action="audio")
        elif lowered.startswith("set brightness to "):
            value = self._extract_number(lowered, default=60)
            result = CommandResult(self.system.set_brightness(value), action="system")
        elif lowered in {"wifi on", "turn wifi on", "enable wifi"}:
            result = CommandResult(self.system.wifi(True), action="system")
        elif lowered in {"wifi off", "turn wifi off", "disable wifi"}:
            result = CommandResult(self.system.wifi(False), action="system")
        elif lowered in {"bluetooth on", "bluetooth off", "open bluetooth", "bluetooth settings"}:
            result = CommandResult(self.system.bluetooth_settings(), action="system")
        elif lowered in {"check updates", "check for updates"}:
            result = CommandResult(self.system.check_updates(), action="updates")
        elif lowered in {"update apps", "upgrade apps", "update everything"}:
            result = CommandResult(self.system.upgrade_apps(), action="updates")
        elif lowered in {"lock pc", "lock system", "lock computer"}:
            result = CommandResult(self.system.lock_pc(), action="system")
        elif lowered in {"sleep pc", "sleep system", "put computer to sleep"}:
            result = CommandResult(self.system.sleep_pc(), action="system")
        elif lowered.startswith("send message to"):
            name = command[len("send message to"):].strip()
            result = CommandResult(self._contact_status(name), action="message")
        elif lowered in {"start focus mode", "focus mode"}:
            result = CommandResult(self._run_focus_mode(), action="routine")
        elif lowered in {"start research mode", "research mode"}:
            result = CommandResult(self._run_research_mode(), action="routine")
        elif lowered in {"start coding mode", "coding mode"}:
            result = CommandResult(self._run_coding_mode(), action="routine")
        elif lowered in {"start cinematic mode", "cinematic mode"}:
            result = CommandResult(self._run_cinematic_mode(), action="routine")
        elif lowered in {"status", "system status"}:
            snapshot = self.snapshot()
            result = CommandResult(
                f"Mode: {snapshot.mode}. Local agent: {'ready' if snapshot.ai_enabled else 'offline'}. "
                f"Voice: {'ready' if snapshot.voice_enabled else 'offline'}. "
                f"System audio: {'ready' if snapshot.audio_enabled else 'limited'}. "
                f"Models: main={self.config.ollama_model}, planner={self.config.planner_model}, "
                f"creative={self.config.creative_model}, fast={self.config.fast_model}.",
                action="status",
            )
        elif lowered.startswith("brainstorm "):
            topic = command[len("brainstorm "):].strip()
            result = CommandResult(self.agent.brainstorm(topic, self.history), action="brainstorm")
        elif lowered.startswith("plan "):
            topic = command[len("plan "):].strip()
            result = CommandResult(self.agent.plan(topic, self.history), action="plan")
        elif lowered.startswith("think with me about "):
            topic = command[len("think with me about "):].strip()
            result = CommandResult(self.agent.think_with_user(topic, self.history), action="think")
        elif lowered.startswith("quick answer "):
            topic = command[len("quick answer "):].strip()
            result = CommandResult(self.agent.quick_think(topic, self.history), action="quick")
        else:
            entities = self.knowledge.extract_entities(command)
            reply = self.agent.reply(command, self.history)
            metadata = {"entities": ", ".join(entities)} if entities else {}
            result = CommandResult(reply=reply, action="agent", metadata=metadata)

        self._remember("assistant", result.reply)
        return result

    def _remember(self, source: str, text: str) -> None:
        self.history.append(ChatMessage(source=source, text=text))

    def _capabilities(self) -> str:
        return (
            "I can act as a multi-model local open-source desktop assistant with Ollama, brainstorm ideas, "
            "build plans, think through problems with you, launch YouTube and Spotify automations, open common "
            "Windows tools, search files and folders, control Wi-Fi and brightness, check for updates, start focus "
            "and research routines, search Google, summarize Wikipedia, save notes, adjust system volume, and listen "
            "for voice input when audio dependencies are installed."
        )

    def _strip_words(self, text: str, words: list[str]) -> str:
        cleaned = text
        for word in words:
            cleaned = cleaned.replace(word, "")
        return cleaned.strip()

    def _google(self, query: str) -> str:
        if not query:
            webbrowser.open("https://www.google.com/")
            return "Opening Google."
        encoded = urllib.parse.quote_plus(query)
        webbrowser.open(f"https://www.google.com/search?q={encoded}")
        return f"Searching Google for {query}."

    def _extract_note(self, command: str) -> str:
        note = command
        for pattern in [r"^save note\s*", r"^take note\s*", r"^note this\s*"]:
            note = re.sub(pattern, "", note, flags=re.IGNORECASE)
        return note.strip() or "Empty note requested."

    def _contact_status(self, name: str) -> str:
        if not name:
            return "Tell me who the message is for."
        number = self.config.contacts.get(name.lower())
        if not number:
            return f"I don't know a saved contact called {name}."
        if phonenumbers is None:
            return f"Contact {name} is saved, but phonenumbers is not installed yet."
        parsed = phonenumbers.parse(number, "IN")
        formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return f"Contact {name} is ready at {formatted}."

    def _search_files(self, query: str) -> str:
        matches = self.system.search_files(query)
        if not matches:
            return f"I couldn't find files or folders matching {query}."
        formatted = "\n".join(matches[:8])
        return f"I found these matches for {query}:\n{formatted}"

    def _extract_number(self, text: str, default: int = 50) -> int:
        numbers = re.findall(r"\d+", text)
        if not numbers:
            return default
        return int(numbers[0])

    def _run_focus_mode(self) -> str:
        actions = [
            self.media.open_spotify(),
            self.media.playlist_for_vibe("deep focus ambient"),
        ]
        return "Focus mode activated. " + " ".join(actions)

    def _run_research_mode(self) -> str:
        actions = [
            self._google("latest breakthroughs in artificial intelligence"),
            self.media.open_site("https://en.wikipedia.org/wiki/Artificial_intelligence", "Wikipedia"),
            self.system.open_app("notepad"),
        ]
        return "Research mode activated. " + " ".join(actions)

    def _run_coding_mode(self) -> str:
        actions = [
            self.media.playlist_for_vibe("programming synthwave"),
            self.media.open_site("https://github.com/", "GitHub"),
            self.media.open_site("https://stackoverflow.com/", "Stack Overflow"),
        ]
        return "Coding mode activated. " + " ".join(actions)

    def _run_cinematic_mode(self) -> str:
        actions = [
            self.media.launch_youtube_mix("epic cinematic soundtrack"),
            self.media.search_spotify("cinematic orchestral playlist"),
        ]
        return "Cinematic mode activated. " + " ".join(actions)
