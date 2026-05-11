from __future__ import annotations

import argparse

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Edith as a local assistant CLI.")
    parser.add_argument("query", nargs="*", help="Optional one-shot query for Edith.")
    parser.add_argument("--no-bootstrap", action="store_true", help="Skip background Ollama/bootstrap startup.")
    parser.add_argument("--quiet-trace", action="store_true", help="Hide thought/action/result trace output.")
    return parser


def main() -> None:
    from edith_app.assistant import EdithAssistant
    from edith_app.config import AppConfig
    from edith_app.services.bootstrap_service import BootstrapService

    parser = build_parser()
    args = parser.parse_args()

    config = AppConfig()
    if not args.no_bootstrap:
        BootstrapService(config).start_async()
    assistant = EdithAssistant(config)

    one_shot = " ".join(args.query).strip()
    if one_shot:
        _run_query(assistant, one_shot, quiet_trace=args.quiet_trace)
        return

    print(assistant.greet())
    print("Type a request, or use 'exit' to leave.")
    while True:
        try:
            command = input("edith> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not command:
            continue
        if command.lower() in {"exit", "quit"}:
            break
        _run_query(assistant, command, quiet_trace=args.quiet_trace)


def _run_query(assistant: EdithAssistant, command: str, quiet_trace: bool) -> None:
    result = assistant.handle(command)
    trace = result.metadata.get("trace", "")
    if trace and not quiet_trace:
        print("Trace:")
        print(trace)
        print()
    print("Answer:")
    print(result.reply)
    print()


if __name__ == "__main__":
    main()
