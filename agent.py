import requests
import json
import os
import shutil
import time
import sys
from datetime import datetime

API_URL = "https://chatjimmy.ai/api/chat"
RATE_LIMIT = 0.5  # seconds between API calls
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.join(SCRIPT_DIR, "workspace")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")

# blackboard is injected into every API call so the model can always see it,
# even as older messages fall out of its context window.
blackboard = ""

SYSTEM_PROMPT = f"""You are a helpful assistant with file access inside a working directory.

All file operations are sandboxed to: {WORKING_DIR}
Use only relative paths (e.g. "notes.txt", "subdir/file.txt"). Absolute paths are not allowed.

## Tools

read_file(path) - Read a file's contents.
write_file(path, content) - Write content to a file (creates or overwrites). Parent directory must exist.
delete_file(path) - Delete a file (not a directory).
delete_dir(path) - Delete a directory and everything inside it.
make_dir(path) - Create a directory (and any parents).
list_files(path) - List files and directories. Use "." for the root.
run_command(description) - Ask the user to run a command or program for you. Provide a clear description of what you need them to run (e.g. "please run: python fizzbuzz.py 15"). This pauses the program and waits for the user. The user will put any output into "output.txt" in the working directory, which you can then read with read_file("output.txt"). Always write your code to a file FIRST, then use this tool to ask the user to run it.
blackboard_write(content) - Overwrite the blackboard with new content. The blackboard persists across the entire conversation and is always visible to you even as older messages scroll out of context.
blackboard_read() - Read the current blackboard contents.

When you want to use a tool, respond with exactly one of these formats on its own line:
TOOL_CALL: read_file("path")
TOOL_CALL: write_file("path", "content here")
TOOL_CALL: delete_file("path")
TOOL_CALL: delete_dir("path")
TOOL_CALL: make_dir("path")
TOOL_CALL: list_files("path")
TOOL_CALL: run_command("description of what to run")
TOOL_CALL: blackboard_write("my notes here")
TOOL_CALL: blackboard_read()

## Rules
- Only call ONE tool at a time. Never chain tool calls with semicolons.
- Do NOT delete files or directories unless the user explicitly asks you to.
- IMPORTANT: At the start of every conversation, BEFORE doing anything else, use blackboard_write() to record: (1) what the user is asking you to do, (2) your plan to accomplish it, (3) a checklist you can refer back to. This keeps you on track.
- Before each tool call, re-read the blackboard to remind yourself what you're doing and why.
- After completing a step, update the blackboard to check it off."""

log_file = None

def log(text):
    if log_file:
        log_file.write(text + "\n")
        log_file.flush()

def safe_path(rel_path):
    """Resolve a relative path and ensure it stays inside WORKING_DIR."""
    rel_path = rel_path.strip("\"'").strip()
    if not rel_path or rel_path == ".":
        return WORKING_DIR
    joined = os.path.normpath(os.path.join(WORKING_DIR, rel_path))
    if not joined.startswith(WORKING_DIR):
        return None
    return joined

def get_system_prompt_with_blackboard():
    if blackboard:
        return SYSTEM_PROMPT + f"\n\n## Current Blackboard\n{blackboard}"
    return SYSTEM_PROMPT + "\n\n## Current Blackboard\n(empty - you should write your task and plan here)"

def call_api(messages):
    resp = requests.post(API_URL, json={
        "messages": messages,
        "chatOptions": {
            "selectedModel": "llama3.1-8B",
            "systemPrompt": get_system_prompt_with_blackboard(),
            "topK": 8,
        },
        "attachment": None,
    })
    resp.raise_for_status()
    raw = resp.text
    text = raw
    if "<|stats|>" in text:
        text = text[:text.index("<|stats|>")]
    return raw, text.strip()

def parse_tool_args(call_body):
    """Rough parser to pull arguments from a tool call string like: func("a", "b")"""
    open_paren = call_body.index("(")
    inner = call_body[open_paren + 1:].rstrip(")")
    args = []
    current = ""
    in_quotes = False
    quote_char = None
    i = 0
    while i < len(inner):
        c = inner[i]
        if not in_quotes and c in ('"', "'"):
            in_quotes = True
            quote_char = c
        elif in_quotes and c == quote_char and (i == 0 or inner[i-1] != "\\"):
            in_quotes = False
        elif not in_quotes and c == ",":
            args.append(current.strip().strip("\"'"))
            current = ""
            i += 1
            continue
        else:
            current += c
        i += 1
    if current.strip():
        args.append(current.strip().strip("\"'"))
    return args

def handle_tool_call(line):
    global blackboard
    body = line.split("TOOL_CALL:", 1)[1].strip()

    if body.startswith("blackboard_write("):
        args = parse_tool_args(body)
        if not args:
            return "[Error]: blackboard_write requires content."
        blackboard = args[0]
        return f"[Blackboard updated]\n{blackboard}"

    elif body.startswith("blackboard_read("):
        if blackboard:
            return f"[Blackboard contents]:\n{blackboard}"
        return "[Blackboard is empty]"

    elif body.startswith("run_command("):
        args = parse_tool_args(body)
        if not args:
            return "[Error]: run_command requires a description."
        description = args[0]
        # create an empty output.txt for the user to fill
        output_path = os.path.join(WORKING_DIR, "output.txt")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("")
        print(f"\n{'='*60}")
        print(f"  AGENT REQUEST: {description}")
        print(f"  Working dir: {WORKING_DIR}")
        print(f"  Put any output into: output.txt")
        print(f"{'='*60}")
        input("  Press Enter when done...")
        print()
        # read back whatever the user put in output.txt
        try:
            with open(output_path, "r", encoding="utf-8", errors="replace") as f:
                output = f.read(50_000)
        except Exception:
            output = ""
        if output.strip():
            return f"[User ran command. Output in output.txt. Contents:]:\n{output}"
        else:
            return "[User ran command. output.txt is empty (no output or user did not write output).]"

    elif body.startswith("read_file("):
        args = parse_tool_args(body)
        resolved = safe_path(args[0])
        if not resolved:
            return "[Error]: Path escapes working directory."
        try:
            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(50_000)
            return f"[File contents of {args[0]}]:\n{content}"
        except Exception as e:
            return f"[Error reading {args[0]}]: {e}"

    elif body.startswith("write_file("):
        args = parse_tool_args(body)
        if len(args) < 2:
            return "[Error]: write_file requires (path, content)."
        resolved = safe_path(args[0])
        if not resolved:
            return "[Error]: Path escapes working directory."
        try:
            content = args[1].replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[Wrote {len(content)} chars to {args[0]}]"
        except Exception as e:
            return f"[Error writing {args[0]}]: {e}"

    elif body.startswith("delete_file("):
        args = parse_tool_args(body)
        resolved = safe_path(args[0])
        if not resolved:
            return "[Error]: Path escapes working directory."
        if os.path.isdir(resolved):
            return f"[Error]: '{args[0]}' is a directory, not a file. Use delete_dir() instead."
        try:
            os.remove(resolved)
            return f"[Deleted {args[0]}]"
        except Exception as e:
            return f"[Error deleting {args[0]}]: {e}"

    elif body.startswith("delete_dir("):
        args = parse_tool_args(body)
        resolved = safe_path(args[0])
        if not resolved:
            return "[Error]: Path escapes working directory."
        if resolved == WORKING_DIR:
            return "[Error]: Cannot delete the root working directory."
        if not os.path.isdir(resolved):
            return f"[Error]: '{args[0]}' is not a directory. Use delete_file() instead."
        try:
            shutil.rmtree(resolved)
            return f"[Deleted directory {args[0]} and all contents]"
        except Exception as e:
            return f"[Error deleting directory {args[0]}]: {e}"

    elif body.startswith("make_dir("):
        args = parse_tool_args(body)
        resolved = safe_path(args[0])
        if not resolved:
            return "[Error]: Path escapes working directory."
        try:
            os.makedirs(resolved, exist_ok=True)
            return f"[Created directory {args[0]}]"
        except Exception as e:
            return f"[Error creating directory {args[0]}]: {e}"

    elif body.startswith("list_files("):
        args = parse_tool_args(body)
        resolved = safe_path(args[0] if args else ".")
        if not resolved:
            return "[Error]: Path escapes working directory."
        try:
            entries = os.listdir(resolved)
            listing = []
            for e in sorted(entries):
                full = os.path.join(resolved, e)
                prefix = "DIR " if os.path.isdir(full) else "FILE"
                listing.append(f"  {prefix}  {e}")
            if not listing:
                return "[Directory is empty]"
            return "[Listing]:\n" + "\n".join(listing)
        except Exception as e:
            return f"[Error listing {args[0] if args else '.'}]: {e}"

    return f"[Error]: Unknown tool call: {body.split('(')[0]}. Available tools: read_file, write_file, delete_file, delete_dir, make_dir, list_files, run_command, blackboard_write, blackboard_read."

def main():
    global log_file

    os.makedirs(WORKING_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"session_{timestamp}.log")
    log_file = open(log_path, "w", encoding="utf-8")

    messages = []
    print("ChatJimmy Agent (llama3.1-8B on Taalas hardware)")
    print(f"Working directory: {WORKING_DIR}")
    print(f"Session log: {log_path}")
    print("Tools: read_file, write_file, delete_file, delete_dir, make_dir, list_files, run_command, blackboard")
    print("Type 'quit' to exit.\n")

    log(f"=== Session started {datetime.now().isoformat()} ===")
    log(f"Working directory: {WORKING_DIR}")
    log("")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Bye!")
                break

            log(f"--- USER ---")
            log(user_input)
            log("")

            messages.append({"role": "user", "content": user_input})

            while True:
                time.sleep(RATE_LIMIT)
                raw, response = call_api(messages)

                log(f"--- ASSISTANT (raw) ---")
                log(raw)
                log("")

                tool_result = None
                tool_line = None
                for line in response.splitlines():
                    line_stripped = line.strip()
                    if line_stripped.startswith("TOOL_CALL:"):
                        tool_line = line_stripped
                        tool_result = handle_tool_call(line_stripped)
                        break

                if tool_result:
                    print(f"  [tool] {tool_line}")
                    log(f"--- TOOL DETECTED ---")
                    log(f"Call: {tool_line}")
                    log(f"Result: {tool_result}")
                    log("")
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": tool_result})
                else:
                    print(f"Bot: {response}\n")
                    messages.append({"role": "assistant", "content": response})
                    break
    finally:
        log(f"\n=== Session ended {datetime.now().isoformat()} ===")
        log_file.close()

if __name__ == "__main__":
    main()
