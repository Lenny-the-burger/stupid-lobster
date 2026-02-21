# Stupid lobster

A minimal agentic coding assistant powered by [ChatJimmy](https://chatjimmy.ai/) (Llama 3.1 8B running on [Taalas](https://taalas.com/) custom silicon) running at a blazing 15 THOUSAND tokens per second. No API keys needed.

![2025_09_10_16_54_16_709377_G0FHZM3WwAAkOOo](https://github.com/user-attachments/assets/b35173c7-79ec-43ba-87a8-c8bf0c55831c)

jimmy generates text at 15 thousand token a second. It also only runs an 8B model. What if we gave it access to your computer?

It rarely does anything good, and likes deleting files. But hey its free.

They call it artifical intelligence, and its definetly got the artifical part down. Dont get IP banned.

## Quick Start

```
pip install requests
python agent.py
```

## How It Works

The agent runs in a loop: you give it a task, it plans on a blackboard, then uses tools to read/write/manage files in a sandboxed `workspace/` directory. It can't run code itself, but it can ask you to run things for it.

## Tools

| Tool | Description |
|------|-------------|
| `read_file(path)` | Read a file |
| `write_file(path, content)` | Create or overwrite a file |
| `delete_file(path)` | Delete a file |
| `delete_dir(path)` | Recursively delete a directory |
| `make_dir(path)` | Create a directory |
| `list_files(path)` | List directory contents |
| `run_command(description)` | Ask the user to run something (human-in-the-loop) |
| `blackboard_write(content)` | Write persistent notes visible across the whole conversation |
| `blackboard_read()` | Read the blackboard |

## Sandboxing

All file operations are locked to the `workspace/` directory. Path traversal attempts (e.g. `../../etc/passwd`) are blocked. The agent cannot execute code directly -- `run_command` pauses and asks you to do it, with output going into `workspace/output.txt`.

## Blackboard

Small models lose track of what they're doing as the conversation grows. The blackboard is injected into the system prompt on every API call, so the model always sees its task and plan regardless of context window limits. The model is instructed to write its plan at the start of every conversation and update it as it works.

## Logging

Every session is logged to `logs/session_YYYYMMDD_HHMMSS.log` with full raw model output, detected tool calls, and results.

## Configuration

Edit the top of `agent.py`:

- `RATE_LIMIT` -- seconds between API calls (default 0.5)
- `WORKING_DIR` -- sandbox directory (default `workspace/` next to the script)
- `chatOptions.selectedModel` -- model to use (default `llama3.1-8B`)
