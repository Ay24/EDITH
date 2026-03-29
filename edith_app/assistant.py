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
from edith_app.services.memory_service import MemoryService
from edith_app.services.notes_service import NotesService
from edith_app.services.system_service import SystemService
from edith_app.services.voice_service import VoiceService
from edith_app.services.whatsapp_service import WhatsAppService

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
        self.memory = MemoryService(config.memory_path)
        self.notes = NotesService(config.notes_path)
        self.system = SystemService()
        self.whatsapp = WhatsAppService()
        self._pending_suggestion: str | None = None
        self._pending_message_contact: str | None = None
        self._suggestion_cooldown_turns = 0

    def snapshot(self) -> AssistantSnapshot:
        return AssistantSnapshot(
            mode="Local Agent Command Center",
            ai_enabled=self.agent.enabled,
            voice_enabled=self.voice.enabled,
            audio_enabled=self.audio.system_audio_enabled,
        )

    def greet(self) -> str:
        remembered = self.memory.recent(limit=4, include_actions={"agent", "brainstorm", "plan", "think", "quick", "note"})
        greeting = (
            f"{self.config.persona.name} online. Local agent, voice controls, media automations, "
            "and desktop routines are ready."
        )
        if remembered:
            greeting += f" I restored {len(remembered)} recent conversation memories."
        self._remember("assistant", greeting)
        return greeting

    def speak(self, text: str) -> None:
        self.audio.speak(text)

    def stop_speaking(self) -> None:
        self.audio.stop()

    def listen_once(self) -> str:
        return self.voice.listen_once()

    def listen_for_command(self) -> str:
        return self.voice.listen_for_command(timeout=self.config.voice_command_timeout)

    def listen_for_interrupt(self) -> str:
        return self.voice.listen_for_interrupt()

    def handle(self, command: str) -> CommandResult:
        command = command.strip()
        lowered = command.lower()
        self._remember("user", command)

        if lowered in {"yes", "yes do it", "do it", "go ahead"} and self._pending_suggestion:
            replay_command = self._pending_suggestion
            self._pending_suggestion = None
            return self.handle(replay_command)

        if lowered in {"no", "nope", "cancel", "not that"} and self._pending_suggestion:
            self._pending_suggestion = None
            self._suggestion_cooldown_turns = 2
            result = CommandResult("Understood. Tell me what you want instead.", action="memory")
            self._remember("assistant", result.reply)
            return result

        if self._pending_suggestion and lowered not in {"yes", "yes do it", "do it", "go ahead", "no", "nope", "cancel", "not that"}:
            self._pending_suggestion = None

        if lowered in {"cancel message", "cancel the message", "never mind"} and self._pending_message_contact:
            contact = self._pending_message_contact
            self._pending_message_contact = None
            result = CommandResult(f"Cancelled the pending message for {contact}.", action="message")
            self._remember("assistant", result.reply)
            return result

        if self._pending_message_contact and lowered not in {"yes", "yes do it", "do it", "go ahead", "no", "nope", "cancel", "not that"}:
            contact = self._pending_message_contact
            self._pending_message_contact = None
            return self._finalize_pending_message(contact, command)

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
        elif "play" in lowered and "on spotify" in lowered:
            query = lowered.replace("play", "", 1).replace("on spotify", "", 1).strip()
            result = CommandResult(self.media.play_spotify(query or "music"), action="spotify")
        elif lowered.startswith("spotify search"):
            query = self._strip_words(lowered, ["spotify search"])
            result = CommandResult(self.media.search_spotify(query or "cinematic soundtrack"), action="spotify")
        elif lowered.startswith("spotify playlist"):
            vibe = self._strip_words(lowered, ["spotify playlist", "for"])
            result = CommandResult(self.media.playlist_for_vibe(vibe or "deep focus"), action="spotify")
        elif lowered.startswith("search google for"):
            query = self._strip_words(lowered, ["search google for"])
            result = CommandResult(self._google(query), action="browser")
        elif lowered in {"latest news", "news", "latest news please"}:
            result = CommandResult(self.system.search_web("latest news today"), action="browser")
        elif lowered.startswith("search for "):
            query = command[len("search for "):].strip()
            result = CommandResult(self._search_files_or_web(query), action="files")
        elif lowered.startswith("search the web for") or lowered.startswith("look up ") or lowered.startswith("browse "):
            query = self._strip_words(lowered, ["search the web for", "look up", "browse"])
            result = CommandResult(self.system.search_web(query), action="browser")
        elif lowered in {"open google", "google"}:
            result = CommandResult(self._google(""), action="browser")
        elif lowered.startswith("open github"):
            result = CommandResult(self.media.open_site("https://github.com/", "GitHub"), action="browser")
        elif lowered.startswith("open stackoverflow"):
            result = CommandResult(self.media.open_site("https://stackoverflow.com/", "Stack Overflow"), action="browser")
        elif lowered.startswith("open gmail"):
            result = CommandResult(self.media.open_site("https://mail.google.com/", "Gmail"), action="browser")
        elif lowered.startswith("open whatsapp"):
            result = CommandResult(self.whatsapp.open_app(), action="system")
        elif self._is_whatsapp_call_command(lowered):
            result = CommandResult(self._start_whatsapp_call(command, video=False), action="message")
        elif self._is_whatsapp_video_call_command(lowered):
            result = CommandResult(self._start_whatsapp_call(command, video=True), action="message")
        elif self._is_whatsapp_send_command(lowered):
            result = CommandResult(self._send_whatsapp_message(command), action="message")
        elif self._is_message_contact_only_command(lowered):
            result = CommandResult(self._start_pending_message(command), action="message")
        elif lowered in {"read my whatsapp messages", "read my messages", "read whatsapp messages"}:
            result = CommandResult(self.whatsapp.read_current_chat(), action="message")
        elif lowered.startswith("open folder "):
            target = command[len("open folder "):].strip()
            result = CommandResult(self.system.open_folder(target), action="files")
        elif self._is_open_item_in_folder_command(command):
            item_name, folder_name = self._parse_open_item_in_folder(command)
            result = CommandResult(self.system.open_item_in_folder(item_name, folder_name), action="files")
        elif lowered.startswith("find file ") or lowered.startswith("find folder "):
            query = command.split(" ", 2)[2].strip()
            result = CommandResult(self._search_files(query), action="files")
        elif self._is_find_item_in_folder_command(command):
            item_name, folder_name = self._parse_find_item_in_folder(command)
            result = CommandResult(self._search_files_in_folder(item_name, folder_name), action="files")
        elif lowered.startswith("find ") and ("on my system" in lowered or "in my system" in lowered):
            query = (
                lowered.replace("find", "", 1)
                .replace("on my system", "")
                .replace("in my system", "")
                .strip()
            )
            result = CommandResult(self._search_files(query), action="files")
        elif lowered.startswith("open calculator"):
            result = CommandResult(self.system.open_app("calculator"), action="system")
        elif lowered.startswith("open notepad"):
            result = CommandResult(self.system.open_app("notepad"), action="system")
        elif lowered.startswith("open settings"):
            result = CommandResult(self.system.open_app("settings"), action="system")
        elif lowered.startswith("open explorer") or lowered.startswith("open files"):
            result = CommandResult(self.system.open_app("explorer"), action="system")
        elif lowered in {"open downloads", "open downloads in files"}:
            result = CommandResult(self.system.open_target("downloads"), action="files")
        elif lowered in {"open documents", "open documents in files"}:
            result = CommandResult(self.system.open_target("documents"), action="files")
        elif lowered in {"open desktop", "open desktop in files"}:
            result = CommandResult(self.system.open_target("desktop"), action="files")
        elif lowered.startswith("go to ") and len(lowered.split()) >= 2:
            target = command[len("go to "):].strip()
            result = CommandResult(self.system.open_target(target), action="browser")
        elif lowered.startswith("open ") and len(lowered.split()) >= 2:
            target = command[len("open "):].strip()
            result = CommandResult(self.system.open_target(target), action="system")
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
        elif self._is_volume_up_command(lowered):
            result = CommandResult(self.audio.adjust_volume(0.1), action="audio")
        elif self._is_volume_down_command(lowered):
            result = CommandResult(self.audio.adjust_volume(-0.1), action="audio")
        elif self._is_set_volume_command(lowered):
            result = CommandResult(self.audio.set_volume(self._extract_number(lowered, default=50)), action="audio")
        elif lowered in {"set volume", "set volume to", "volume", "change volume"}:
            result = CommandResult("Tell me a volume level, for example: set volume to 60.", action="audio")
        elif lowered in {"mute", "mute volume", "mute audio", "turn off volume"}:
            result = CommandResult(self.audio.mute(), action="audio")
        elif lowered in {"unmute", "unmute volume", "unmute audio", "turn on volume"}:
            result = CommandResult(self.audio.unmute(), action="audio")
        elif self._is_brightness_command(lowered):
            value = self._extract_number(lowered, default=60)
            result = CommandResult(self.system.set_brightness(value), action="system")
        elif lowered in {"wifi on", "turn wifi on", "enable wifi"}:
            result = CommandResult(self.system.wifi(True), action="system")
        elif lowered in {"wifi off", "turn wifi off", "disable wifi"}:
            result = CommandResult(self.system.wifi(False), action="system")
        elif lowered in {
            "bluetooth on",
            "bluetooth off",
            "turn on bluetooth",
            "turn off bluetooth",
            "enable bluetooth",
            "disable bluetooth",
            "open bluetooth",
            "bluetooth settings",
        }:
            result = CommandResult(self._handle_bluetooth_command(lowered), action="system")
        elif lowered in {"check updates", "check for updates"} or lowered.startswith("check for upda"):
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
        elif lowered.startswith("brainstorm ") or lowered.startswith("brain storm "):
            topic = re.sub(r"^brain\s*storm\s+", "", command, flags=re.IGNORECASE).strip()
            result = CommandResult(self.agent.brainstorm(topic, self.history), action="brainstorm")
        elif lowered in {"brainstorm", "brain stor", "brain storm"}:
            result = CommandResult("Tell me what to brainstorm.", action="brainstorm")
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
            if self._should_suggest(command):
                similar = self.memory.similar(command, threshold=0.9)
                if similar is not None:
                    self._pending_suggestion = similar.command
                    result = CommandResult(
                        f"This sounds similar to when you said '{similar.command}'. "
                        "Is that what you want to achieve again?",
                        action="memory",
                    )
                    self._remember("assistant", result.reply)
                    return result
            entities = self.knowledge.extract_entities(command)
            reply = self.agent.reply(self._contextualize_prompt(command), self._context_history())
            metadata = {"entities": ", ".join(entities)} if entities else {}
            result = CommandResult(reply=reply, action="agent", metadata=metadata)

        result.reply = self._polish_reply(result.reply, result.action)
        self._remember("assistant", result.reply)
        if self._should_store_interaction(command, result):
            self.memory.remember(command, result.reply, result.action)
        if self._suggestion_cooldown_turns > 0:
            self._suggestion_cooldown_turns -= 1
        return result

    def _remember(self, source: str, text: str) -> None:
        self.history.append(ChatMessage(source=source, text=text))

    def _capabilities(self) -> str:
        return (
            "I can act as a multi-model local open-source desktop assistant with Ollama, brainstorm ideas, "
            "build plans, think through problems with you, launch YouTube and Spotify automations, open common "
            "Windows tools, search files and folders, control Wi-Fi and brightness, check for updates, start focus "
            "and research routines, search Google, summarize Wikipedia, save notes, remember past chat intentions, "
            "adjust system volume, and listen for voice input when audio dependencies are installed."
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

    def _send_whatsapp_message(self, command: str) -> str:
        contact_pattern = self._contact_name_pattern()
        match = re.match(
            rf"(?:send message to|message|text)\s+(.+?)\s+(?:saying|that|telling them)\s+(.+)",
            command,
            flags=re.IGNORECASE,
        )
        if not match and contact_pattern:
            match = re.match(
                rf"({contact_pattern})\s+(?:saying|that|telling them)\s+(.+)",
                command,
                flags=re.IGNORECASE,
            )
        if not match:
            return "Say it like: message primary_contact saying I am on the way."
        name = match.group(1).strip()
        message = match.group(2).strip()
        if not name or not message:
            return "I need both a contact name and a message."

        resolved_name = self._resolve_whatsapp_name(name)
        if self._looks_incomplete_message(message):
            self._pending_message_contact = resolved_name
            return f"I caught {resolved_name}. Continue your message and I'll send it."
        return self.whatsapp.send_message(resolved_name, message)

    def _start_whatsapp_call(self, command: str, video: bool) -> str:
        patterns = [
            r"(?:call|voice call|ring)\s+(.+?)\s+(?:on whatsapp|in whatsapp|through whatsapp)$",
            r"(?:call|voice call|ring)\s+(.+)$",
            r"(?:video call)\s+(.+?)\s+(?:on whatsapp|in whatsapp|through whatsapp)$",
            r"(?:video call)\s+(.+)$",
        ]
        name = ""
        for pattern in patterns:
            match = re.match(pattern, command, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                break
        if not name:
            return "Tell me who to call on WhatsApp."
        resolved_name = self._resolve_whatsapp_name(name)
        if video:
            return self.whatsapp.video_call(resolved_name)
        return self.whatsapp.voice_call(resolved_name)

    def _start_pending_message(self, command: str) -> str:
        match = re.match(r"(?:send message to|message|text)\s+(.+)", command, flags=re.IGNORECASE)
        if not match:
            return "Tell me who the message is for."
        name = match.group(1).strip()
        resolved_name = self._resolve_whatsapp_name(name)
        self._pending_message_contact = resolved_name
        return f"What should I send to {resolved_name}?"

    def _finalize_pending_message(self, contact: str, message: str) -> CommandResult:
        cleaned = message.strip()
        if not cleaned:
            return CommandResult(f"I didn't catch the message for {contact}.", action="message")
        reply = self.whatsapp.send_message(contact, cleaned)
        return CommandResult(reply, action="message")

    def _resolve_contact_name(self, spoken_name: str) -> str | None:
        lowered = spoken_name.lower().strip()
        for saved_name in self.config.contacts:
            if saved_name.lower() == lowered:
                return saved_name
        return None

    def _resolve_whatsapp_name(self, spoken_name: str) -> str:
        lowered = spoken_name.lower().strip()
        configured = self.config.whatsapp_display_names.get(lowered)
        if configured:
            return configured
        resolved_contact = self._resolve_contact_name(spoken_name)
        if resolved_contact is not None:
            configured = self.config.whatsapp_display_names.get(resolved_contact.lower())
            if configured:
                return configured
            return resolved_contact
        return spoken_name.strip()

    def _contact_name_pattern(self) -> str:
        names = sorted(self.config.contacts.keys(), key=len, reverse=True)
        return "|".join(re.escape(name) for name in names)

    def _search_files(self, query: str) -> str:
        matches = self.system.search_files(query)
        if not matches:
            return f"I couldn't find files or folders matching {query}."
        formatted = "\n".join(matches[:8])
        return f"I found these matches for {query}:\n{formatted}"

    def _search_files_in_folder(self, query: str, folder: str) -> str:
        matches = self.system.search_within_folder(query, folder, limit=8)
        if not matches:
            return f"I couldn't find {query} inside {folder}."
        formatted = "\n".join(matches[:8])
        return f"I found these matches for {query} inside {folder}:\n{formatted}"

    def _search_files_or_web(self, query: str) -> str:
        matches = self.system.search_files(query)
        if matches:
            formatted = "\n".join(matches[:6])
            return f"I found these local matches for {query}:\n{formatted}"
        return self.system.search_web(query)

    def _contextualize_prompt(self, command: str) -> str:
        relevant = self.memory.relevant(command, limit=3)
        if not relevant:
            return command
        memory_lines = [
            f"- Earlier request: {item.command} | Edith replied: {item.reply}"
            for item in relevant
        ]
        return (
            "Use this remembered context if it helps, but do not override the user's current intent.\n"
            "Remembered context:\n"
            + "\n".join(memory_lines)
            + f"\nCurrent user request: {command}"
        )

    def _context_history(self) -> list[ChatMessage]:
        history = list(self.history[-10:])
        recent_memory = self.memory.recent(limit=4, include_actions={"agent", "brainstorm", "plan", "think", "quick", "note"})
        remembered_messages: list[ChatMessage] = []
        for item in recent_memory:
            remembered_messages.append(ChatMessage(source="assistant", text=f"Remembered user request: {item.command}"))
            remembered_messages.append(ChatMessage(source="assistant", text=f"Remembered reply: {item.reply}"))
        return (remembered_messages + history)[-14:]

    def _handle_bluetooth_command(self, lowered: str) -> str:
        if lowered in {"bluetooth off", "turn off bluetooth", "disable bluetooth"}:
            return self.system.bluetooth(False)
        if lowered in {"bluetooth on", "turn on bluetooth", "enable bluetooth"}:
            return self.system.bluetooth(True)
        return self.system.bluetooth_settings()

    def _extract_number(self, text: str, default: int = 50) -> int:
        numbers = re.findall(r"\d+", text)
        if not numbers:
            return default
        return int(numbers[0])

    def _is_volume_up_command(self, text: str) -> bool:
        phrases = (
            "increase volume",
            "turn up the volume",
            "turn the volume up",
            "volume up",
            "raise the volume",
            "make it louder",
            "make the sound louder",
            "boost the volume",
        )
        return any(phrase in text for phrase in phrases)

    def _is_volume_down_command(self, text: str) -> bool:
        phrases = (
            "decrease volume",
            "turn down the volume",
            "turn the volume down",
            "volume down",
            "lower the volume",
            "make it quieter",
            "make the sound quieter",
            "reduce the volume",
        )
        return any(phrase in text for phrase in phrases)

    def _is_set_volume_command(self, text: str) -> bool:
        phrases = (
            "set volume to",
            "volume to",
            "make the volume",
            "change the volume to",
        )
        return any(phrase in text for phrase in phrases) and any(char.isdigit() for char in text)

    def _is_brightness_command(self, text: str) -> bool:
        phrases = (
            "set brightness",
            "brightness to",
            "make the screen brighter",
            "make screen brighter",
            "increase brightness",
            "raise brightness",
            "make the screen dimmer",
            "make screen dimmer",
            "decrease brightness",
            "lower brightness",
            "turn brightness up",
            "turn brightness down",
        )
        return any(phrase in text for phrase in phrases)

    def _is_open_item_in_folder_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("open ") and " in " in lowered and not lowered.startswith("open folder ")

    def _parse_open_item_in_folder(self, text: str) -> tuple[str, str]:
        cleaned = re.sub(r"^open\s+", "", text, flags=re.IGNORECASE).strip()
        item_name, folder_name = re.split(r"\s+in\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return item_name.strip(), folder_name.strip()

    def _is_find_item_in_folder_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("find ") and " in " in lowered and " on my system" not in lowered and " in my system" not in lowered

    def _parse_find_item_in_folder(self, text: str) -> tuple[str, str]:
        cleaned = re.sub(r"^find\s+", "", text, flags=re.IGNORECASE).strip()
        item_name, folder_name = re.split(r"\s+in\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return item_name.strip(), folder_name.strip()

    def _should_store(self, action: str) -> bool:
        return action not in {"system", "updates", "audio", "clock", "status", "files"}

    def _should_store_interaction(self, command: str, result: CommandResult) -> bool:
        lowered = command.lower().strip()
        reply = result.reply.lower().strip()

        if not self._should_store(result.action):
            return False
        if len(lowered) < 8:
            return False
        if self._looks_incomplete(lowered) or self._looks_incomplete_message(lowered):
            return False
        if result.action in {"memory", "help"}:
            return False

        failure_markers = (
            "i couldn't",
            "i could not",
            "i can't",
            "i cannot",
            "unavailable",
            "didn't catch",
            "did not catch",
            "tell me ",
            "need both",
            "need a",
            "not recognized",
            "not available",
            "still warming up",
            "starting up",
            "try again",
            "error",
            "offline",
            "no speech captured",
            "no update information",
            "i don't know a saved contact",
        )
        if any(marker in reply for marker in failure_markers):
            return False

        command_noise = (
            "brain stor",
            "set volume",
            "set volume to",
            "check for upda",
        )
        if lowered in command_noise:
            return False

        return True

    def _should_suggest(self, command: str) -> bool:
        lowered = command.lower().strip()
        if not lowered:
            return False
        if self._suggestion_cooldown_turns > 0:
            return False
        if len(lowered) < 18:
            return False
        if self._looks_incomplete(lowered):
            return False
        if self._is_message_related(lowered):
            return False
        prefixes = (
            "open ",
            "find file ",
            "find folder ",
            "open folder ",
            "message ",
            "text ",
            "send message to",
            "set brightness",
            "wifi ",
            "bluetooth ",
            "increase volume",
            "decrease volume",
            "check updates",
            "update apps",
            "lock pc",
            "sleep pc",
        )
        return not lowered.startswith(prefixes)

    def _looks_incomplete(self, text: str) -> bool:
        incomplete_endings = (
            " a",
            " an",
            " the",
            " this is a",
            " saying",
            " send",
            " message",
            " text",
            " open",
            " search",
        )
        return any(text.endswith(ending) for ending in incomplete_endings)

    def _is_whatsapp_send_command(self, text: str) -> bool:
        starters = ("send message to ", "message ", "text ")
        if text.startswith(starters) and any(word in text for word in (" saying ", " that ", " telling them ")):
            return True
        return self._starts_with_contact(text) and any(word in text for word in (" saying ", " that ", " telling them "))

    def _is_whatsapp_call_command(self, text: str) -> bool:
        return (
            (text.startswith("call ") or text.startswith("voice call ") or text.startswith("ring "))
            and "video call" not in text
        )

    def _is_whatsapp_video_call_command(self, text: str) -> bool:
        return text.startswith("video call ")

    def _is_message_contact_only_command(self, text: str) -> bool:
        starters = ("send message to ", "message ", "text ")
        return text.startswith(starters) and not any(word in text for word in (" saying ", " that ", " telling them "))

    def _is_message_related(self, text: str) -> bool:
        if self._is_whatsapp_send_command(text) or self._is_message_contact_only_command(text):
            return True
        if " saying " in text or " telling them " in text:
            return any(name in text for name in self.config.contacts)
        return False

    def _starts_with_contact(self, text: str) -> bool:
        lowered = text.lower().strip()
        return any(lowered.startswith(f"{name} ") or lowered == name for name in self.config.contacts)

    def _looks_incomplete_message(self, text: str) -> bool:
        cleaned = text.lower().strip()
        if len(cleaned) < 10:
            return True
        incomplete_endings = (" a", " an", " the", " this is a", " this is", " that this is a")
        return any(cleaned.endswith(ending) for ending in incomplete_endings)

    def _polish_reply(self, text: str, action: str) -> str:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return text
        if action in {"audio", "system", "files", "clock", "updates", "status", "message"}:
            return cleaned
        if action in {"agent", "quick"}:
            sentences = re.split(r"(?<=[.!?])\s+", cleaned)
            return " ".join(sentences[:3]).strip()
        if action in {"plan", "brainstorm", "think"}:
            lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
            if len(lines) <= 5:
                return "\n".join(lines)
            return "\n".join(lines[:5])
        return cleaned

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
