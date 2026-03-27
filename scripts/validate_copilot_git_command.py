import json
import re
import shlex
import sys


COMMIT_PREFIX_RE = re.compile(r"^(feat|fix|chore)(\([^)]+\))?!?:\s+\S")
WRITE_COMMANDS = {
    "add",
    "commit",
    "push",
    "merge",
    "rebase",
    "cherry-pick",
    "reset",
    "restore",
    "clean",
}
SHELL_SEPARATORS = {"&&", "||", ";", "|"}


def emit(decision=None, reason=None, additional_context=None):
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
        }
    }
    if decision:
        payload["hookSpecificOutput"]["permissionDecision"] = decision
    if reason:
        payload["hookSpecificOutput"]["permissionDecisionReason"] = reason
    if additional_context:
        payload["hookSpecificOutput"]["additionalContext"] = additional_context
    sys.stdout.write(json.dumps(payload))


def load_payload():
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def collect_command_strings(tool_input):
    commands = []

    def walk(value):
        if isinstance(value, dict):
            command = value.get("command")
            if isinstance(command, str):
                commands.append(command)

            args = value.get("args")
            if isinstance(args, list) and args:
                rendered = " ".join(str(item) for item in args)
                if rendered:
                    commands.append(rendered)

            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(tool_input)
    return commands


def tokenize(command):
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def is_git_token(token):
    return token == "git" or token.endswith("/git") or token.endswith("\\git.exe")


def extract_commit_message(tokens, start_index):
    index = start_index + 2
    while index < len(tokens):
        token = tokens[index]

        if token in SHELL_SEPARATORS:
            break

        if token in {"-m", "--message"}:
            if index + 1 < len(tokens):
                return tokens[index + 1]
            return None

        if token.startswith("--message="):
            return token.split("=", 1)[1]

        if token.startswith("-m") and token != "-m":
            return token[2:]

        index += 1

    return None


def inspect_command(command):
    tokens = tokenize(command)
    ask_reason = None

    for index, token in enumerate(tokens[:-1]):
        if not is_git_token(token):
            continue

        subcommand = tokens[index + 1]
        if subcommand not in WRITE_COMMANDS:
            continue

        if subcommand == "commit":
            if "--amend" in tokens[index + 2:]:
                return "deny", "Git commit --amend is blocked by repository policy. Create a new commit unless the user explicitly requests amend."

            message = extract_commit_message(tokens, index)
            if not message:
                return "deny", "Git commits must use a non-interactive explicit message like 'feat: ...', 'fix: ...', or 'chore: ...'."

            subject = message.splitlines()[0].strip()
            if not COMMIT_PREFIX_RE.match(subject):
                return "deny", "Git commit subjects must start with feat:, fix:, or chore:."

            ask_reason = "Confirm the staged scope and commit message before creating git history."
            continue

        if ask_reason is None:
            ask_reason = f"Confirm the git {subcommand} operation before modifying repository state."

    if ask_reason:
        return "ask", ask_reason

    return None, None


def main():
    payload = load_payload()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if not tool_name or not tool_input:
        emit()
        return

    commands = collect_command_strings(tool_input)
    if not commands:
        emit()
        return

    final_decision = None
    final_reason = None

    for command in commands:
        if "git" not in command:
            continue

        decision, reason = inspect_command(command)
        if decision == "deny":
            emit("deny", reason)
            return
        if decision == "ask":
            final_decision = "ask"
            final_reason = reason

    if final_decision:
        emit(final_decision, final_reason)
        return

    emit()


if __name__ == "__main__":
    main()