from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from edith_app.core.agent_loop import AgentLoop
from edith_app.core.session_memory import SessionMemory
from edith_app.core.task_queue import TaskQueue
from edith_app.core.tool_registry import ToolRegistry
from edith_app.config import AppConfig
from edith_app.models import AssistantSnapshot, ChatMessage, CommandResult
from edith_app.services.agent_service import AgentService
from edith_app.services.audio_service import AudioService
from edith_app.services.connectivity_service import ConnectivityService
from edith_app.services.knowledge_service import KnowledgeService
from edith_app.services.logging_service import get_logger
from edith_app.services.media_service import MediaService
from edith_app.services.memory_service import MemoryService
from edith_app.services.notes_service import NotesService
from edith_app.services.self_improve_service import SelfImproveService
from edith_app.services.system_service import SystemService
from edith_app.services.vision_service import VisionService
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
        self.logger = get_logger("edith.assistant", config.runtime_log_path)
        self.agent = AgentService(config)
        self.audio = AudioService()
        self.voice = VoiceService(config)
        self.connectivity = ConnectivityService()
        self.knowledge = KnowledgeService(
            user_agent=f"{config.persona.name}/3.0 desktop assistant",
            lightweight_mode=config.lightweight_mode,
        )
        self.media = MediaService(config)
        self.memory = MemoryService(config.memory_path)
        self.session_memory = SessionMemory(config.session_memory_path)
        self.task_queue = TaskQueue(config.cowork_tasks_path)
        self.notes = NotesService(config.notes_path)
        self.self_improve = SelfImproveService(
            project_root=str(config.project_root),
            telemetry_path=config.telemetry_path,
            overrides_path=config.self_improve_overrides_path,
            agent=self.agent,
        )
        self.vision = VisionService(config)
        self.system = SystemService(self.vision, config.organization_manifest_path)
        self.whatsapp = WhatsAppService()
        self.cowork = AgentLoop(
            self.agent,
            ToolRegistry(str(config.project_root)),
            self.session_memory,
        )
        self._pending_suggestion: str | None = None
        self._pending_message_contact: str | None = None
        self._pending_organization: tuple[str, bool] | None = None
        self._suggestion_cooldown_turns = 0

    def snapshot(self) -> AssistantSnapshot:
        return AssistantSnapshot(
            mode="Local Agent Command Center + Coworker Mode",
            ai_enabled=self.agent.enabled,
            voice_enabled=self.voice.enabled,
            audio_enabled=self.audio.system_audio_enabled,
        )

    def greet(self) -> str:
        remembered = self.memory.recent(limit=4, include_actions={"agent", "brainstorm", "plan", "think", "quick", "note"})
        greeting = (
            f"{self.config.persona.name} online. Local agent, voice controls, media automations, "
            "desktop routines, and coworker mode are ready."
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
        self.logger.info("handle command: %s", lowered[:180])

        if lowered in {"yes", "yes do it", "do it", "go ahead"} and self._pending_suggestion:
            replay_command = self._pending_suggestion
            self._pending_suggestion = None
            return self.handle(replay_command)

        if lowered in {"yes", "yes do it", "do it", "go ahead", "apply", "confirm"} and self._pending_organization:
            target, by_context = self._pending_organization
            self._pending_organization = None
            reply = self.system.organize_folder_by_context(target) if by_context else self.system.organize_folder(target)
            result = CommandResult(reply, action="files")
            self._remember("assistant", result.reply)
            return result

        if lowered in {"no", "nope", "cancel", "not that"} and self._pending_suggestion:
            self._pending_suggestion = None
            self._suggestion_cooldown_turns = 2
            result = CommandResult("Understood. Tell me what you want instead.", action="memory")
            self._remember("assistant", result.reply)
            return result

        if lowered in {"no", "nope", "cancel", "not that"} and self._pending_organization:
            self._pending_organization = None
            result = CommandResult("Okay, I cancelled that organization run.", action="files")
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

        if self._pending_organization and lowered not in {"yes", "yes do it", "do it", "go ahead", "apply", "confirm", "no", "nope", "cancel", "not that"}:
            self._pending_organization = None

        compound_reply = self._try_handle_compound_command(command)
        if compound_reply is not None:
            result = CommandResult(compound_reply, action="routine")
            result.reply = self._polish_reply(result.reply, result.action)
            self._remember("assistant", result.reply)
            return result

        if not command:
            result = CommandResult("I need a command to work with.")
        elif lowered in {"help", "capabilities", "what can you do"}:
            result = CommandResult(self._capabilities(), action="help")
        elif lowered.startswith("cowork on "):
            goal = command[len("cowork on "):].strip()
            run = self.cowork.run(goal, self._context_history(), mode="cowork")
            result = CommandResult(run.reply, action="cowork", metadata={"plan": run.plan, "verified": run.summary, "edit_brief": run.edit_brief})
        elif lowered.startswith("analyze workspace") or lowered.startswith("analyze this project"):
            goal = command.split(" ", 2)[-1].strip() if len(command.split()) > 2 else "analyze the current workspace and surface the main findings"
            run = self.cowork.run(goal, self._context_history(), mode="workspace")
            result = CommandResult(run.reply, action="cowork", metadata={"plan": run.plan, "verified": run.summary, "edit_brief": run.edit_brief})
        elif lowered.startswith("coding task "):
            goal = command[len("coding task "):].strip()
            run = self.cowork.run(goal, self._context_history(), mode="coding")
            result = CommandResult(run.reply, action="cowork", metadata={"plan": run.plan, "verified": run.summary, "edit_brief": run.edit_brief})
        elif lowered.startswith("propose edit for "):
            goal = command[len("propose edit for "):].strip()
            run = self.cowork.run(goal, self._context_history(), mode="edit")
            result = CommandResult(run.reply, action="cowork", metadata={"plan": run.plan, "verified": run.summary, "edit_brief": run.edit_brief})
        elif lowered.startswith("browser task "):
            goal = command[len("browser task "):].strip()
            run = self.cowork.run(goal, self._context_history(), mode="browser")
            result = CommandResult(run.reply, action="cowork", metadata={"plan": run.plan, "verified": run.summary, "edit_brief": run.edit_brief})
        elif lowered.startswith("queue task "):
            title = command[len("queue task "):].strip()
            task = self.task_queue.add(title)
            result = CommandResult(f"Queued cowork task: {task.title}.", action="cowork")
        elif lowered in {"show tasks", "show cowork tasks", "list tasks", "task list"}:
            result = CommandResult(self.task_queue.summary(), action="cowork")
        elif lowered in {"next task", "next cowork task"}:
            task = self.task_queue.next_task()
            if task is None:
                result = CommandResult("No pending cowork tasks right now.", action="cowork")
            else:
                result = CommandResult(f"Next cowork task: {task.title}.", action="cowork")
        elif lowered.startswith("complete task "):
            title = command[len("complete task "):].strip()
            task = self.task_queue.complete(title)
            if task is None:
                result = CommandResult(f"I couldn't find a queued task matching {title}.", action="cowork")
            else:
                result = CommandResult(f"Marked task as done: {task.title}.", action="cowork")
        elif lowered in {"clear done tasks", "clear completed tasks"}:
            cleared = self.task_queue.clear_done()
            result = CommandResult(f"Cleared {cleared} completed cowork task{'s' if cleared != 1 else ''}.", action="cowork")
        elif lowered in {"what were we working on", "resume cowork", "resume our work"}:
            result = CommandResult(self._resume_cowork_summary(), action="cowork")
        elif lowered.startswith("open youtube"):
            result = CommandResult(self.media.open_youtube_home(), action="youtube")
        elif lowered in {"youtube", "open yt", "yt"}:
            result = CommandResult(self.media.open_youtube_home(), action="youtube")
        elif "play anything interesting" in lowered or "play something interesting" in lowered:
            result = CommandResult(self.media.launch_youtube_mix("trending cinematic music"), action="youtube")
        elif "youtube mix" in lowered:
            query = self._strip_words(lowered, ["youtube mix", "for"])
            result = CommandResult(self.media.launch_youtube_mix(query or "focus music"), action="youtube")
        elif "play" in lowered and "on youtube" in lowered:
            query = lowered.replace("play", "", 1).replace("on youtube", "", 1).strip()
            result = CommandResult(self.media.search_youtube(query or "music"), action="youtube")
        elif lowered.startswith("play "):
            query = lowered.replace("play", "", 1).strip()
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
            result = CommandResult(self._online_or_local(self._google(query), "search Google"), action="browser")
        elif lowered in {"latest news", "news", "latest news please"}:
            result = CommandResult(self._online_or_local(self.system.search_web("latest news today"), "fetch the latest news"), action="browser")
        elif lowered.startswith("search for "):
            query = command[len("search for "):].strip()
            result = CommandResult(self._search_files_or_web(query), action="files")
        elif lowered.startswith("search the web for") or lowered.startswith("look up ") or lowered.startswith("browse "):
            query = self._strip_words(lowered, ["search the web for", "look up", "browse"])
            result = CommandResult(self._online_or_local(self.system.search_web(query), "search the web"), action="browser")
        elif lowered in {"open google", "google"}:
            result = CommandResult(self._online_or_local(self._google(""), "open Google"), action="browser")
        elif lowered.startswith("open github"):
            result = CommandResult(self.media.open_site("https://github.com/", "GitHub"), action="browser")
        elif lowered.startswith("open stack"):
            result = CommandResult(self.media.open_site("https://stackoverflow.com/", "Stack Overflow"), action="browser")
        elif lowered.startswith("open stack overflow"):
            result = CommandResult(self.media.open_site("https://stackoverflow.com/", "Stack Overflow"), action="browser")
        elif lowered.startswith("open stackoverflow"):
            result = CommandResult(self.media.open_site("https://stackoverflow.com/", "Stack Overflow"), action="browser")
        elif lowered.startswith("open gmail"):
            result = CommandResult(self.media.open_site("https://mail.google.com/", "Gmail"), action="browser")
        elif lowered.startswith("open whatsapp"):
            result = CommandResult(self.whatsapp.open_app(), action="system")
        elif lowered in {"self improve status", "self-improve status", "improve status"}:
            result = CommandResult(self.self_improve.status_report(), action="status")
        elif lowered in {"self improve apply", "self-improve apply", "apply improve", "apply self improve", "improve apply"}:
            run_goal = "improve runtime speed, stability, and voice reliability with safe local tuning"
            result = CommandResult(self.self_improve.run(run_goal, self._context_history(), apply=True), action="status")
        elif lowered.startswith("propose skill for "):
            goal = command[len("propose skill for "):].strip()
            result = CommandResult(self.self_improve.propose_skill(goal, self._context_history()), action="status")
        elif lowered.startswith("self improve ") or lowered.startswith("self-improve "):
            run_goal = re.sub(r"^self[\s-]?improve\s+", "", command, flags=re.IGNORECASE).strip()
            result = CommandResult(self.self_improve.run(run_goal or "improve runtime reliability", self._context_history(), apply=False), action="status")
        elif lowered in {"self improve", "self-improve"}:
            run_goal = "improve runtime speed, stability, and voice reliability with safe local tuning"
            result = CommandResult(self.self_improve.run(run_goal, self._context_history(), apply=False), action="status")
        elif lowered in {"run preflight", "preflight", "system preflight"}:
            result = CommandResult(self.preflight_report(), action="status")
        elif lowered in {"export debug bundle", "export diagnostics", "debug bundle"}:
            result = CommandResult(self.export_debug_bundle(), action="status")
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
        elif self._is_preview_organize_target_command(command):
            target, by_context = self._parse_organize_target_command(command, prefix="preview")
            result = CommandResult(self.system.preview_organization(target, by_context=by_context), action="files")
        elif self._is_analyze_target_command(command):
            target, by_context = self._parse_analyze_target_command(command)
            if by_context:
                result = CommandResult(self.system.analyze_folder_context(target), action="files")
            else:
                result = CommandResult(self.system.folder_clutter_report(target), action="files")
        elif self._is_organize_target_command(command):
            target, by_context = self._parse_organize_target_command(command)
            result = CommandResult(self._queue_organization(target, by_context=by_context), action="files")
        elif lowered in {"analyze desktop", "analyze my desktop", "desktop analysis", "desktop status"}:
            result = CommandResult(self.system.folder_clutter_report("desktop"), action="files")
        elif lowered in {"analyze downloads", "downloads analysis", "analyze my downloads"}:
            result = CommandResult(self.system.folder_clutter_report("downloads"), action="files")
        elif lowered in {"analyze desktop by context", "context analyze desktop", "analyze desktop context"}:
            result = CommandResult(self.system.analyze_folder_context("desktop"), action="files")
        elif lowered in {"analyze downloads by context", "context analyze downloads", "analyze downloads context"}:
            result = CommandResult(self.system.analyze_folder_context("downloads"), action="files")
        elif lowered in {"preview organize desktop", "preview desktop organization"}:
            result = CommandResult(self.system.preview_organization("desktop", by_context=False), action="files")
        elif lowered in {"preview organize desktop by context", "preview desktop context organization"}:
            result = CommandResult(self.system.preview_organization("desktop", by_context=True), action="files")
        elif lowered in {"preview organize downloads", "preview downloads organization"}:
            result = CommandResult(self.system.preview_organization("downloads", by_context=False), action="files")
        elif lowered in {"preview organize downloads by context", "preview downloads context organization"}:
            result = CommandResult(self.system.preview_organization("downloads", by_context=True), action="files")
        elif lowered in {"organize desktop", "clean desktop", "declutter desktop", "sort desktop files"}:
            result = CommandResult(self._queue_organization("desktop", by_context=False), action="files")
        elif lowered in {"organize downloads", "clean downloads", "declutter downloads"}:
            result = CommandResult(self._queue_organization("downloads", by_context=False), action="files")
        elif lowered in {"organize desktop by context", "context organize desktop", "smart organize desktop"}:
            result = CommandResult(self._queue_organization("desktop", by_context=True), action="files")
        elif lowered in {"organize downloads by context", "context organize downloads", "smart organize downloads"}:
            result = CommandResult(self._queue_organization("downloads", by_context=True), action="files")
        elif lowered in {"organise desktop", "organise desktop by context", "organise downloads", "organise downloads by context"}:
            normalized = lowered.replace("organise", "organize")
            if normalized.endswith("by context"):
                target = "desktop" if "desktop" in normalized else "downloads"
                result = CommandResult(self._queue_organization(target, by_context=True), action="files")
            else:
                target = "desktop" if "desktop" in normalized else "downloads"
                result = CommandResult(self._queue_organization(target, by_context=False), action="files")
        elif lowered in {"organize downloads with context", "organize desktop with context"}:
            target = "desktop" if "desktop" in lowered else "downloads"
            result = CommandResult(self._queue_organization(target, by_context=True), action="files")
        elif lowered in {"undo last organization", "undo organization", "revert last organization"}:
            result = CommandResult(self.system.undo_last_organization(), action="files")
        elif lowered.startswith("analyze folder "):
            target = command[len("analyze folder "):].strip()
            result = CommandResult(self.system.folder_clutter_report(target), action="files")
        elif lowered.startswith("analyze context in folder "):
            target = command[len("analyze context in folder "):].strip()
            result = CommandResult(self.system.analyze_folder_context(target), action="files")
        elif lowered.startswith("analyze folder context "):
            target = command[len("analyze folder context "):].strip()
            result = CommandResult(self.system.analyze_folder_context(target), action="files")
        elif lowered.startswith("preview organize folder by context "):
            target = command[len("preview organize folder by context "):].strip()
            result = CommandResult(self.system.preview_organization(target, by_context=True), action="files")
        elif lowered.startswith("preview organize folder "):
            target = command[len("preview organize folder "):].strip()
            result = CommandResult(self.system.preview_organization(target, by_context=False), action="files")
        elif lowered.startswith("organize folder "):
            target = command[len("organize folder "):].strip()
            result = CommandResult(self._queue_organization(target, by_context=False), action="files")
        elif lowered.startswith("organize folder by context "):
            target = command[len("organize folder by context "):].strip()
            result = CommandResult(self._queue_organization(target, by_context=True), action="files")
        elif lowered.startswith("smart organize folder "):
            target = command[len("smart organize folder "):].strip()
            result = CommandResult(self._queue_organization(target, by_context=True), action="files")
        elif self._is_move_item_command(command):
            item_name, folder_name = self._parse_move_item_command(command)
            result = CommandResult(self.system.move_item(item_name, folder_name), action="files")
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
            result = CommandResult(self._summarize_topic(topic), action="knowledge")
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
        elif lowered in {"cowork mode", "co work mode", "co-work mode"}:
            result = CommandResult("Cowork mode is ready. Say: cowork on <goal> to begin.", action="cowork")
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
            smalltalk = self._smalltalk_reply(command)
            if smalltalk is not None:
                result = CommandResult(reply=smalltalk, action="agent")
                result.reply = self._polish_reply(result.reply, result.action)
                self._remember("assistant", result.reply)
                return result
            if self._is_very_short_ambiguous(lowered):
                result = CommandResult(
                    "I heard you. Want me to search it, play it, or open something specific?",
                    action="quick",
                )
                result.reply = self._polish_reply(result.reply, result.action)
                self._remember("assistant", result.reply)
                return result
            entities = self._safe_extract_entities(command)
            reply = self._safe_agent_reply(command)
            metadata = {"entities": ", ".join(entities)} if entities else {}
            result = CommandResult(reply=reply, action="agent", metadata=metadata)

        result.reply = self._polish_reply(result.reply, result.action)
        self._remember("assistant", result.reply)
        if self._should_store_interaction(command, result):
            self.memory.remember(command, result.reply, result.action)
        if self._suggestion_cooldown_turns > 0:
            self._suggestion_cooldown_turns -= 1
        return result

    def _safe_extract_entities(self, command: str) -> list[str]:
        try:
            return self.knowledge.extract_entities(command)
        except Exception:
            return []

    def _safe_agent_reply(self, command: str) -> str:
        try:
            lowered = command.lower().strip()
            if len(lowered.split()) <= 7:
                reply = self.agent.quick_think(
                    "Respond as a natural desktop assistant in 1-2 short sentences. "
                    f"User message: {command}",
                    self._context_history(),
                )
            else:
                reply = self.agent.reply(self._contextualize_prompt(command), self._context_history())
            return self._sanitize_model_output(reply)
        except Exception:
            self.logger.exception("safe agent reply failed")
            return "I hit a temporary model issue, but I am still here. Please try that once more."

    def _sanitize_model_output(self, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return text
        cleaned = re.sub(r"^(user|assistant|system)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(user|assistant|system)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "").strip()
        return cleaned

    def _smalltalk_reply(self, command: str) -> str | None:
        lowered = command.lower().strip()
        normalized = re.sub(r"[^a-z0-9\s]", " ", lowered)
        normalized = " ".join(normalized.split())
        smalltalk_map = {
            "hi": "Hey. I am here with you.",
            "hii": "Hey. I am here with you.",
            "hiii": "Hey. I am here with you.",
            "hay": "Hey. I am here with you.",
            "heyy": "Hey. I am here with you.",
            "helo": "Hello. Ready when you are.",
            "hello": "Hello. Ready when you are.",
            "hey": "Hey. What should we do next?",
            "how are you": "I am doing great and ready to help.",
            "good morning": "Good morning. Let's make this a productive run.",
            "good afternoon": "Good afternoon. I am ready to help.",
            "good evening": "Good evening. What should I handle first?",
            "thanks": "Always. Want me to do the next step too?",
            "thank you": "Anytime. I can keep going.",
            "what else can you do": "I can control apps, media, files, routines, cowork tasks, and system actions. Tell me one thing and I will do it.",
            "can you play anything interesting for me": "Sure. I can start a cinematic mix on YouTube or a deep-focus playlist on Spotify. Say which one you want.",
        }
        if normalized in smalltalk_map:
            return smalltalk_map[normalized]
        if normalized.startswith("hi ") or normalized.startswith("hello ") or normalized.startswith("hey "):
            return "Hey. I am listening."
        return None

    def _is_very_short_ambiguous(self, lowered: str) -> bool:
        if not lowered:
            return False
        if any(ch.isdigit() for ch in lowered):
            return False
        if len(lowered.split()) > 2:
            return False
        known_prefixes = (
            "open ",
            "play ",
            "set ",
            "turn ",
            "run ",
            "export ",
            "search ",
            "find ",
            "send ",
            "message ",
            "call ",
            "wifi",
            "bluetooth",
            "preflight",
            "debug",
            "self improve",
        )
        if lowered.startswith(known_prefixes):
            return False
        whitelist = {"hi", "hii", "hiii", "hay", "hey", "hello", "thanks", "thank you", "youtube", "spotify", "google"}
        if lowered in whitelist:
            return False
        return True

    def _try_handle_compound_command(self, command: str) -> str | None:
        lowered = command.lower().strip()
        if len(lowered) < 12:
            return None
        if " and " not in lowered and " then " not in lowered:
            return None
        action_markers = ("open ", "search ", "search for ", "play ", "go to ")
        if sum(1 for marker in action_markers if marker in lowered) < 2:
            return None

        parts = re.split(r"\s+(?:and then|then|and)\s+", command, flags=re.IGNORECASE)
        parts = [part.strip(" ,.") for part in parts if part.strip(" ,.")]
        if len(parts) < 2:
            return None

        context: dict[str, Any] = {"site": None}
        replies: list[str] = []
        handled_steps = 0
        for part in parts[:5]:
            step_reply = self._execute_compound_step(part, context)
            if step_reply is None:
                continue
            handled_steps += 1
            replies.append(step_reply)
        if handled_steps < 2:
            return None
        return " ".join(replies)

    def _execute_compound_step(self, step: str, context: dict[str, Any]) -> str | None:
        lowered = step.lower().strip()
        if lowered.startswith("open "):
            target = step[5:].strip()
            if not target:
                return None
            context["site"] = self._infer_site(target)
            return self.system.open_target(target)
        if lowered.startswith("go to "):
            target = step[6:].strip()
            if not target:
                return None
            context["site"] = self._infer_site(target)
            return self.system.open_target(target)
        if lowered.startswith("play "):
            query = re.sub(r"^play\s+", "", step, flags=re.IGNORECASE).strip()
            if "on youtube" in lowered:
                context["site"] = "youtube"
                query = re.sub(r"\s+on youtube$", "", query, flags=re.IGNORECASE).strip()
                return self.media.search_youtube(query or "music")
            if "on spotify" in lowered:
                context["site"] = "spotify"
                query = re.sub(r"\s+on spotify$", "", query, flags=re.IGNORECASE).strip()
                return self.media.play_spotify(query or "music")
            active = context.get("site")
            if active == "youtube":
                return self.media.search_youtube(query or "music")
            if active == "spotify":
                return self.media.play_spotify(query or "music")
            return self.media.search_youtube(query or "music")
        if lowered.startswith("search for ") or lowered.startswith("search "):
            query = re.sub(r"^search(?:\s+for)?\s+", "", step, flags=re.IGNORECASE).strip()
            if not query:
                return None
            active = context.get("site")
            if "youtube" in lowered or active == "youtube":
                context["site"] = "youtube"
                return self.media.search_youtube(query)
            if "spotify" in lowered or active == "spotify":
                context["site"] = "spotify"
                return self.media.search_spotify(query)
            if "amazon" in lowered or active == "amazon":
                context["site"] = "amazon"
                encoded = urllib.parse.quote_plus(query)
                webbrowser.open(f"https://www.amazon.in/s?k={encoded}")
                return f"Searching Amazon for {query}."
            return self._search_files_or_web(query)
        return None

    def _infer_site(self, target: str) -> str | None:
        lowered = target.lower().strip()
        if "youtube" in lowered:
            return "youtube"
        if "spotify" in lowered:
            return "spotify"
        if "amazon" in lowered:
            return "amazon"
        if lowered in {"chrome", "google chrome"}:
            return "browser"
        return None

    def _remember(self, source: str, text: str) -> None:
        self.history.append(ChatMessage(source=source, text=text))

    def _capabilities(self) -> str:
        return (
            "I can act as a multi-model local open-source desktop assistant with Ollama, work fully locally for chat, "
            "voice control, memory, notes, files, and system actions, brainstorm ideas, build plans, think through "
            "problems with you, launch YouTube and Spotify automations, open common Windows tools, search files and "
            "folders, organize desktops and folders, move files into place, control Wi-Fi and brightness, check for "
            "updates, search Google, summarize Wikipedia, adjust system volume, analyze the workspace like a coding "
            "teammate, inspect files, run compile checks, keep session-level coworker memory, and run a safe "
            "self-improvement cycle that tunes runtime reliability without retraining models."
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

    def _online_or_local(self, online_reply: str, capability: str) -> str:
        if self.connectivity.is_online():
            return online_reply
        return (
            f"Internet is offline, so I can't {capability} right now. "
            "I can still help with local apps, files, notes, memory, and offline chat."
        )

    def _summarize_topic(self, topic: str) -> str:
        if not self.connectivity.is_online():
            return (
                f"Internet is offline, so I can't reach Wikipedia for {topic} right now. "
                "I can still search your local files or notes if you want."
            )
        return self.knowledge.summarize_topic(topic)

    def _resume_cowork_summary(self) -> str:
        items = self.session_memory.recent(limit=3)
        if not items:
            return "We do not have a coworker session yet. Say something like: cowork on improving startup performance."
        lines = []
        for item in items:
            lines.append(f"- {item.goal}: {item.summary}")
        queue_summary = self.task_queue.summary()
        return "Recent cowork context:\n" + "\n".join(lines) + "\n\n" + queue_summary

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

    def _queue_organization(self, target: str, by_context: bool) -> str:
        preview = self.system.preview_organization(target, by_context=by_context)
        self._pending_organization = (target, by_context)
        mode = "context" if by_context else "file-type"
        return (
            f"{preview}\n\n"
            f"Preview ready ({mode}). Say 'yes' to apply this organization, or 'no' to cancel."
        )

    def preflight_report(self) -> str:
        model_ready, model_status = self.agent.runtime_status()
        voice_ready = self.voice.enabled
        audio_ready = self.audio.system_audio_enabled
        online = self.connectivity.is_online()
        return (
            "Preflight status:\n"
            f"- Model runtime: {'READY' if model_ready else 'DEGRADED'} ({model_status})\n"
            f"- Voice recognition: {'READY' if voice_ready else 'UNAVAILABLE'}\n"
            f"- System audio control: {'READY' if audio_ready else 'LIMITED'}\n"
            f"- Internet: {'ONLINE' if online else 'OFFLINE'}\n"
            f"- Command timeout: {self.config.command_timeout_seconds}s"
        )

    def export_debug_bundle(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = Path(self.config.data_dir)
        bundle_dir = root / "debug"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle_dir / f"edith_debug_{timestamp}.zip"

        snapshot = {
            "timestamp": timestamp,
            "model_status": self.agent.runtime_status()[1],
            "voice_enabled": self.voice.enabled,
            "audio_enabled": self.audio.system_audio_enabled,
            "online": self.connectivity.is_online(),
            "models": {
                "main": self.config.ollama_model,
                "planner": self.config.planner_model,
                "creative": self.config.creative_model,
                "fast": self.config.fast_model,
            },
            "recent_history": [
                {"source": item.source, "text": item.text, "timestamp": item.timestamp.isoformat()}
                for item in self.history[-20:]
            ],
        }

        snapshot_path = root / f"debug_snapshot_{timestamp}.json"
        snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        include_paths = [
            snapshot_path,
            Path(self.config.memory_path),
            Path(self.config.session_memory_path),
            Path(self.config.notes_path),
            Path(self.config.telemetry_path),
        ]
        try:
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
                for path in include_paths:
                    if path.exists() and path.is_file():
                        zipf.write(path, arcname=path.name)
            return f"Debug bundle exported to {bundle_path}."
        except Exception as exc:
            return f"I couldn't export the debug bundle: {exc}"
        finally:
            try:
                if snapshot_path.exists():
                    snapshot_path.unlink()
            except Exception:
                pass

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

    def _is_move_item_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered.startswith("move ") and " to " in lowered

    def _parse_move_item_command(self, text: str) -> tuple[str, str]:
        cleaned = re.sub(r"^move\s+", "", text, flags=re.IGNORECASE).strip()
        item_name, folder_name = re.split(r"\s+to\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return item_name.strip(), folder_name.strip()

    def _is_analyze_target_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("analyze workspace", "analyze this project", "analyze desktop", "analyze downloads")):
            return False
        return lowered.startswith("analyze ") and ("folder " in lowered or "\\" in text or ":/" in lowered or ":\\\\" in lowered or lowered.endswith(("desktop", "downloads", "documents", "pictures", "music", "videos")))

    def _parse_analyze_target_command(self, text: str) -> tuple[str, bool]:
        cleaned = re.sub(r"^analyze\s+", "", text, flags=re.IGNORECASE).strip()
        by_context = False
        cleaned = re.sub(r"^folder\s+", "", cleaned, flags=re.IGNORECASE).strip()
        if re.search(r"\s+by context$", cleaned, flags=re.IGNORECASE):
            by_context = True
            cleaned = re.sub(r"\s+by context$", "", cleaned, flags=re.IGNORECASE).strip()
        elif re.search(r"\s+context$", cleaned, flags=re.IGNORECASE):
            by_context = True
            cleaned = re.sub(r"\s+context$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned, by_context

    def _is_organize_target_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("organize desktop", "organize downloads", "organize folder ", "organize folder by context ", "smart organize folder ", "preview organize ")):
            return False
        return lowered.startswith(("organize ", "smart organize ", "clean ", "declutter ")) and ("\\" in text or ":/" in lowered or ":\\\\" in lowered or any(lowered.endswith(name) for name in ("desktop", "downloads", "documents", "pictures", "music", "videos")))

    def _is_preview_organize_target_command(self, text: str) -> bool:
        lowered = text.lower().strip()
        if lowered.startswith(("preview organize desktop", "preview organize downloads", "preview organize folder ", "preview desktop")):
            return False
        return lowered.startswith("preview organize ") and ("\\" in text or ":/" in lowered or ":\\\\" in lowered or any(lowered.endswith(name) for name in ("desktop", "downloads", "documents", "pictures", "music", "videos")))

    def _parse_organize_target_command(self, text: str, prefix: str | None = None) -> tuple[str, bool]:
        cleaned = text.strip()
        if prefix == "preview":
            cleaned = re.sub(r"^preview\s+organize\s+", "", cleaned, flags=re.IGNORECASE).strip()
        else:
            cleaned = re.sub(r"^(?:smart\s+organize|organize|clean|declutter)\s+", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^folder\s+", "", cleaned, flags=re.IGNORECASE).strip()
        by_context = False
        if re.search(r"\s+by context$", cleaned, flags=re.IGNORECASE):
            by_context = True
            cleaned = re.sub(r"\s+by context$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned, by_context

    def _should_store(self, action: str) -> bool:
        return action not in {"system", "updates", "audio", "clock", "status", "files", "cowork"}

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
        if action == "cowork":
            return cleaned
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
