"""Jean Grey terminal entry point for chat, agent, and local voice modes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
import threading
from typing import Sequence

from localpilot.config import Settings
from localpilot.models.base import ChatMessage, ModelUnavailableError
from localpilot.models.model_manager import check_compatibility, create_adapter, memory_snapshot

SYSTEM_PROMPT = "You are Jean Grey. Be concise, accurate, and never claim an action you did not perform."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jean-grey", description="Jean Grey local AI runtime")
    parser.add_argument("command", nargs="?", choices=("chat", "agent", "voice", "mcp", "browser"), default="chat")
    parser.add_argument("--check", action="store_true", help="check selected subsystem readiness")
    parser.add_argument("--prompt", help="send one prompt and exit")
    parser.add_argument("--profile", choices=("lightweight", "12b", "training"), default="lightweight")
    parser.add_argument("--push-to-talk", action="store_true", help="record only while explicitly active (default)")
    parser.add_argument("--speak-responses", action="store_true", help="synthesize final summaries")
    parser.add_argument("--hands-free", action="store_true", help="explicitly activate repeated voice turns")
    parser.add_argument("--wake-word", action="store_true", help="use local wake word when a verified model is configured")
    parser.add_argument("--mute", action="store_true", help="start hands-free microphone muted")
    parser.add_argument("--language", choices=("auto", "hi", "en", "hinglish"), help="preferred reply language")
    parser.add_argument("--config", type=Path, help="MCP configuration path")
    parser.add_argument("--topic", help="bounded browser research topic")
    parser.add_argument("--source", action="append", default=[], help="approved source URL (repeatable)")
    parser.add_argument("--report", type=Path, help="report path under the approved report root")
    parser.add_argument("--format", choices=("markdown", "csv"), default="markdown")
    return parser


def build_demo_runtime(settings: Settings):
    """Build the Milestone 2 verified demonstration runtime used by text and voice."""
    from localpilot.agent.executor import Executor, ToolRegistry
    from localpilot.agent.permissions import PermissionPolicy
    from localpilot.agent.planner import StaticPlanner
    from localpilot.agent.runtime import AgentRuntime
    from localpilot.agent.types import Plan, PlanStep
    from localpilot.tools.mock import ReadFixtureTool, RecoverableFailureTool, WriteReportTool

    output = settings.data_dir / "demo"; output.mkdir(parents=True, exist_ok=True)
    report = output / "report.txt"
    fixture_root = Path(__file__).resolve().parents[1] / "resources"
    registry = ToolRegistry()
    registry.register(ReadFixtureTool(fixture_root)); registry.register(RecoverableFailureTool(1)); registry.register(WriteReportTool())
    plan = Plan((PlanStep("read_fixture", {"name": "demo.txt"}, {"name": "demo.txt"}),
                 PlanStep("recoverable_failure", {}, {"recovered": True}),
                 PlanStep("write_report", {"path": str(report), "content": "{request}"}, {"exists": True})))
    # Bind the request at execution time without introducing a separate voice runtime.
    class RequestPlanner(StaticPlanner):
        def plan(self, request: str):
            bound = Plan(tuple(PlanStep(s.tool,
                {k: (request if v == "{request}" else v) for k, v in s.arguments.items()}, s.expected)
                for s in self._plan.steps))
            return bound
    return AgentRuntime(RequestPlanner(plan), Executor(registry, PermissionPolicy(output))), report


def run_agent(settings: Settings, args: argparse.Namespace) -> int:
    request = args.prompt or "Jean Grey deterministic agent demo"
    urls = tuple(args.source) or tuple(re.findall(r"https?://[^\s,]+", request))
    topic = args.topic or request
    if urls and (args.topic or "research" in request.lower()):
        extension = ".md" if args.format == "markdown" else ".csv"
        report = args.report or settings.report_root / f"research-{int(time.time())}{extension}"
        try: task, statuses = execute_research(settings, args.config or settings.mcp_config_path,
                                               topic, urls, report, args.format)
        except Exception as exc:
            print(f"Jean Grey research error: {exc}", file=sys.stderr); return 4
        report_result = next((event.result for event in reversed(task.history) if event.tool == "report.create"), None)
        print(json.dumps({"task": task.report(), "report": report_result,
                          "servers": [status.detail for status in statuses]}, indent=2))
        return 0 if task.state.value == "COMPLETED" else 4
    return run_agent_demo(settings, request)


def run_agent_demo(settings: Settings, request: str) -> int:
    from localpilot.agent.types import TaskState
    runtime, report = build_demo_runtime(settings); task = runtime.run(request)
    print(json.dumps(task.report(), indent=2))
    print(f"Report: {report}" if report.exists() else "Report was not created")
    return 0 if task.state == TaskState.COMPLETED else 4


def run_mcp_check(settings: Settings, config_path: Path, *, browser_only: bool = False) -> int:
    """Connect and discover only; never invoke a discovered tool."""
    from dataclasses import asdict
    from localpilot.agent.executor import ToolRegistry
    from localpilot.browser.tools import register_browser_tools
    from localpilot.mcp.config import McpConfigError, load_mcp_config
    from localpilot.mcp.registry import McpManager

    try: config = load_mcp_config(config_path)
    except McpConfigError as exc:
        print(json.dumps({"configured": False, "path": str(config_path), "error": str(exc)}, indent=2)); return 3
    registry = ToolRegistry(); manager = McpManager(config)
    try:
        statuses = manager.connect_enabled(registry); aliases: dict[str, list[str]] = {}
        for name, client in manager.clients.items():
            if client.connected and client.config.browser:
                aliases[name] = list(register_browser_tools(client, registry, settings.browser_max_content_chars))
        payload = {"configured": True, "path": str(config_path), "servers": [asdict(item) for item in statuses],
                   "browser_aliases": aliases, "diagnostic_only": True}
        print(json.dumps(payload, indent=2))
        relevant = [item for item in statuses if not browser_only or config.servers[item.name].browser]
        return 0 if relevant and all(item.connected for item in relevant if item.enabled) and any(item.enabled for item in relevant) else 3
    finally: manager.close()


def execute_research(settings: Settings, config_path: Path, topic: str, source_urls: tuple[str, ...],
                     report_path: Path, format_name: str = "markdown"):
    from localpilot.agent.executor import Executor, ToolRegistry
    from localpilot.agent.permissions import PermissionPolicy
    from localpilot.agent.runtime import AgentRuntime
    from localpilot.browser.reports import OverwriteResearchReportTool, ResearchReportTool
    from localpilot.browser.research import ResearchPlanner, ResearchRequest
    from localpilot.browser.tools import register_browser_tools
    from localpilot.mcp.config import load_mcp_config
    from localpilot.mcp.registry import McpManager

    config = load_mcp_config(config_path); registry = ToolRegistry(); manager = McpManager(config)
    statuses = manager.connect_enabled(registry)
    browser_clients = [client for client in manager.clients.values() if client.connected and client.config.browser]
    aliases: tuple[str, ...] = ()
    for client in browser_clients: aliases += register_browser_tools(client, registry, settings.browser_max_content_chars)
    if "browser.navigate" not in aliases or "browser.get_page_content" not in aliases:
        manager.close(); raise RuntimeError(f"Playwright MCP browser tools unavailable; statuses={statuses}")
    registry.register(ResearchReportTool(settings.report_root)); registry.register(OverwriteResearchReportTool(settings.report_root))
    request = ResearchRequest(topic, source_urls, report_path, format_name)
    planner = ResearchPlanner(request, max_pages=settings.browser_max_pages, max_actions=settings.browser_max_actions)
    runtime = AgentRuntime(planner, Executor(registry, PermissionPolicy(settings.report_root)))
    try: return runtime.run(f"Research {topic}"), statuses
    finally: manager.close()


def execute_browser_search(settings: Settings, config_path: Path, query: str, runtime_hook=None):
    """Run a search page through the same MCP registry, policy, runtime, and verifier."""
    from localpilot.agent.executor import Executor, ToolRegistry
    from localpilot.agent.permissions import PermissionPolicy
    from localpilot.agent.runtime import AgentRuntime
    from localpilot.browser.search import SearchPlanner, SearchRequest
    from localpilot.browser.tools import register_browser_tools
    from localpilot.mcp.config import load_mcp_config
    from localpilot.mcp.registry import McpManager

    config = load_mcp_config(config_path); registry = ToolRegistry(); manager = McpManager(config)
    statuses = manager.connect_enabled(registry); aliases: tuple[str, ...] = ()
    for client in manager.clients.values():
        if client.connected and client.config.browser:
            aliases += register_browser_tools(client, registry, settings.browser_max_content_chars)
    if "browser.navigate" not in aliases or "browser.get_page_content" not in aliases:
        manager.close(); raise RuntimeError(f"Playwright MCP browser tools unavailable; statuses={statuses}")
    runtime = AgentRuntime(SearchPlanner(SearchRequest(query, settings.search_base_url)),
                           Executor(registry, PermissionPolicy(settings.report_root)))
    task = runtime.create_task(f"Search browser for {query}")
    if runtime_hook is not None: runtime_hook(runtime, task)
    try: return runtime.run_task(task), statuses
    finally: manager.close()


def run_browser(settings: Settings, args: argparse.Namespace) -> int:
    config_path = args.config or settings.mcp_config_path
    if args.check or not args.topic:
        return run_mcp_check(settings, config_path, browser_only=True)
    extension = ".md" if args.format == "markdown" else ".csv"
    report = args.report or settings.report_root / f"research-report{extension}"
    try: task, statuses = execute_research(settings, config_path, args.topic, tuple(args.source), report, args.format)
    except Exception as exc:
        print(f"Jean Grey browser error: {exc}", file=sys.stderr); return 4
    report_result = next((event.result for event in reversed(task.history) if event.tool == "report.create"), None)
    print(json.dumps({"task": task.report(), "report": report_result,
                      "servers": [status.detail for status in statuses]}, indent=2))
    return 0 if task.state.value == "COMPLETED" else 4


def _voice_providers(settings: Settings):
    from localpilot.voice.audio_input import SoundDeviceAudioInput
    from localpilot.voice.audio_output import SoundDeviceAudioOutput
    from localpilot.voice.speech_to_text import FasterWhisperProvider
    from localpilot.voice.text_to_speech import MultilingualPiperProvider, PiperProvider
    default_tts = PiperProvider(settings.piper_executable, settings.piper_voice_path,
                                speaking_rate=settings.voice_rate)
    hindi_tts = (PiperProvider(settings.piper_executable, settings.hindi_piper_voice_path,
                               speaking_rate=settings.voice_rate, required_language="hi")
                 if settings.hindi_piper_voice_path else None)
    return (SoundDeviceAudioInput(), FasterWhisperProvider(settings.stt_model_path),
            MultilingualPiperProvider(default_tts, hindi_tts), SoundDeviceAudioOutput())


def run_voice(settings: Settings, args: argparse.Namespace) -> int:
    from localpilot.agent.types import TaskState
    from localpilot.voice.health import voice_health
    from localpilot.voice.providers import VoiceError
    from localpilot.voice.intent import parse_browser_search
    from localpilot.voice.language import VoiceLanguage, concise_status, detect_language
    from localpilot.voice.session import AgentReply, VoiceSession
    from localpilot.voice.wake_word import OpenWakeWordProvider, UnavailableWakeWordProvider, WakeWordSettings

    audio_input, stt, tts, output = _voice_providers(settings)
    wake_word = OpenWakeWordProvider(WakeWordSettings(settings.wake_word_model_path,
                                                       settings.wake_word_threshold))
    health = voice_health(audio_input, stt, tts, output, offline=settings.offline, wake_word=wake_word)
    if args.check:
        print(json.dumps(health, indent=2)); return 0 if all(
            health[key]["available"] for key in ("audio_input", "speech_to_text", "text_to_speech", "audio_output")) else 3
    if "hindi_text_to_speech" in health and not health["hindi_text_to_speech"]["available"]:
        print(f"Hindi speech unavailable: {health['hindi_text_to_speech']['detail']}. Hindi text remains available.")

    runtime, _report = build_demo_runtime(settings)
    active_task = [None]
    active_execution = [None]
    preferred_language = [VoiceLanguage(args.language or settings.preferred_voice_language)]
    def cancel_active_task() -> None:
        if active_execution[0] is not None:
            active_runtime, task = active_execution[0]
            active_runtime.cancel(task)
    def agent_handler(text: str) -> AgentReply:
        research_report: Path | None = None
        urls = tuple(re.findall(r"https?://[^\s,]+", text))
        search_intent = parse_browser_search(text)
        if search_intent is not None and settings.mcp_config_path.is_file():
            try: task, _statuses = execute_browser_search(settings, settings.mcp_config_path, search_intent.query,
                lambda active_runtime, active: active_execution.__setitem__(0, (active_runtime, active)))
            except Exception as exc:
                return AgentReply(f"Browser search unavailable: {type(exc).__name__}. Koi result claim nahi kiya gaya.", "FAILED")
        elif "research" in text.lower() and urls and settings.mcp_config_path.is_file():
            research_report = settings.report_root / f"voice-research-{int(time.time())}.md"
            try: task, _statuses = execute_research(settings, settings.mcp_config_path, text, urls, research_report)
            except Exception as exc:
                return AgentReply(f"Research could not start: {type(exc).__name__}. No browser success is claimed.", "FAILED")
        else:
            task = runtime.run(text)
        active_task[0] = task
        if task.state == TaskState.COMPLETED:
            language = (preferred_language[0] if preferred_language[0] != VoiceLanguage.AUTO
                        else detect_language(text))
            if search_intent is not None:
                detail = ("The search page was verified and observed results are visible. I will not claim a price until source pages are compared."
                          if language == VoiceLanguage.ENGLISH else
                          "खोज परिणाम सत्यापित हैं। स्रोत पृष्ठों की तुलना किए बिना मैं कीमत का दावा नहीं करूँगी।"
                          if language == VoiceLanguage.HINDI else
                          "Search results verify ho gaye aur screen par sources dikh rahe hain. Source pages compare kiye bina main price claim nahi karungi.")
                summary = concise_status("COMPLETED", language, detail)
            else:
                summary = concise_status("COMPLETED", language,
                    f"{task.completed_steps} verified steps complete hue." if language != VoiceLanguage.ENGLISH
                    else f"{task.completed_steps} verified steps completed.")
            if research_report is not None: summary += f" Verified report: {research_report}."
        elif task.state == TaskState.WAITING_FOR_APPROVAL:
            summary = "Task is waiting for explicit approval. No sensitive action was executed."
        else:
            summary = f"Task {task.state.value.lower()}: {task.failure_reason or 'no verified completion'}"
        print(json.dumps(task.report(), indent=2))
        for event in task.history:
            tool = f" tool={event.tool}" if event.tool else ""
            print(f"[{event.state.value}] step={event.step}{tool}: {event.event}")
        print(summary)
        return AgentReply(summary, task.state.value, task.state == TaskState.WAITING_FOR_APPROVAL)

    session = VoiceSession(audio_input, stt, tts, output, agent_handler,
                           speak_responses=args.speak_responses)
    try:
        if args.prompt is not None:
            turn = session.process_text_fallback(args.prompt)
            if turn.error: print(f"Jean Grey voice: {turn.error}", file=sys.stderr); return 4
            session.wait_for_playback()
            return 0 if turn.reply and turn.reply.status == "COMPLETED" else 4
        input_health = health["audio_input"]; stt_health = health["speech_to_text"]
        if not input_health["available"] or not stt_health["available"]:
            print("Voice input is unavailable. Keyboard fallback is active.")
            print(f"Input: {input_health['detail']}; STT: {stt_health['detail']}")
            text = input("task> ").strip()
            turn = session.process_text_fallback(text)
            if turn.error: print(turn.error, file=sys.stderr); return 4
            return 0
        hands_free = args.hands_free or settings.hands_free
        if hands_free and args.wake_word:
            wake_health = wake_word.health()
            if not wake_health.available:
                print(f"Wake word unavailable: {wake_health.detail}")
                print("Falling back to clearly labeled push-to-talk mode.")
            else:
                from localpilot.voice.hands_free import HandsFreeConversation, ConversationState
                conversation = HandsFreeConversation(wake_word, session,
                    preferred_language=preferred_language[0], task_cancel=cancel_active_task,
                    language_changed=lambda selected: preferred_language.__setitem__(0, selected))
                conversation.set_muted(args.mute)
                if args.mute: print("Microphone is muted. Restart without --mute or use push-to-talk fallback."); return 3
                print("Wake microphone active locally. Say: Hello Jean Grey. Ctrl+C exits.")
                if not conversation.wait_for_wake(): return 4
                while conversation.state != ConversationState.STOPPED:
                    print("Listening for one command...")
                    audio = audio_input.capture_utterance(conversation.cancel_event)
                    def hands_free_review(transcript):
                        print(f"Transcript [{transcript.language or 'unknown'}]: {transcript.text}")
                        if not transcript.uncertain: return transcript.text
                        edited = input("Low-confidence transcript. Enter=accept, edit it, or /cancel: ").strip()
                        return None if edited.lower() == "/cancel" else (edited or transcript.text)
                    conversation.handle_audio(audio, hands_free_review)
                return 0
        while True:
            input("Press Enter to start push-to-talk (Ctrl+C to stop): ")
            stop, capture_cancel = threading.Event(), threading.Event(); captured = []; failures = []
            def capture() -> None:
                try: captured.append(audio_input.capture(stop, capture_cancel))
                except VoiceError as exc: failures.append(str(exc))
            worker = threading.Thread(target=capture, name="jean-grey-audio-input", daemon=True); worker.start()
            input("Recording. Press Enter to stop: "); stop.set(); worker.join(timeout=10)
            if worker.is_alive(): capture_cancel.set(); worker.join(timeout=1); print("Recording did not stop safely.", file=sys.stderr); return 4
            if failures: print(failures[0], file=sys.stderr); return 4
            print("Transcription processing locally...")
            def review(transcript: str) -> str | None:
                print(f"Transcript: {transcript}")
                edited = input("Press Enter to confirm, type an edit, or /cancel: ").strip()
                return None if edited.lower() == "/cancel" else (edited or transcript)
            turn = session.process(captured[0], review)
            if turn.error: print(turn.error, file=sys.stderr)
            session.wait_for_playback()
            if not hands_free: return 0 if turn.reply else 4
            if input("Hands-free mode active. Enter=listen again, /stop=stop: ").strip().lower() == "/stop": return 0
    except (EOFError, KeyboardInterrupt):
        cancel_active_task(); session.cancel(); print("\nVoice session cancelled."); return 130
    finally:
        wake_word.close()
        session.close()


def run_chat(settings: Settings, args: argparse.Namespace) -> int:
    resources = memory_snapshot(); compatibility = check_compatibility(args.profile, resources)
    print(f"Jean Grey | backend={settings.backend} | model={settings.model} | offline={settings.offline}")
    print(f"RAM available={resources.available_ram_bytes / 1024**3:.1f} GiB | {compatibility.reason}")
    if not compatibility.compatible: return 2
    adapter = create_adapter(settings); healthy, detail = adapter.health(); print(f"Backend: {detail}")
    if args.check: return 0 if healthy else 3
    if not healthy: return 3
    history = [ChatMessage("system", SYSTEM_PROMPT)]
    if args.prompt is not None:
        history.append(ChatMessage("user", args.prompt))
        for fragment in adapter.stream_chat(history): print(fragment, end="", flush=True)
        print(); return 0
    print("Type /exit to quit. No conversation is sent to cloud services.")
    while True:
        try: text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt): print(); break
        if text.lower() in {"/exit", "/quit"}: break
        if not text: continue
        history.append(ChatMessage("user", text)); print("jean> ", end="", flush=True); answer = ""
        for fragment in adapter.stream_chat(history): answer += fragment; print(fragment, end="", flush=True)
        print(); history.append(ChatMessage("assistant", answer))
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "agent": return run_agent(settings, args)
        if args.command == "voice": return run_voice(settings, args)
        if args.command == "mcp": return run_mcp_check(settings, args.config or settings.mcp_config_path)
        if args.command == "browser": return run_browser(settings, args)
        return run_chat(settings, args)
    except (ValueError, OSError, ModelUnavailableError) as exc:
        print(f"Jean Grey error: {exc}", file=sys.stderr); return 1


def main() -> None: raise SystemExit(run())


if __name__ == "__main__": main()
