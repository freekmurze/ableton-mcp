# Ableton AI

Control Ableton Live from an AI assistant like Claude. You describe what you want in plain language, and it builds it in your Live set: tracks, instruments, effects, MIDI clips, automation, and mixing. Around 130 commands covering most of the Live Object Model.

You describe, it builds, you listen and judge. The assistant has no ears, so it handles the mechanical work while you keep the taste.

## What you can do with it

Ask for a sound and get it built:

```text
Build a dark ambient pad on a new track. Slow attack, long release,
a filter behind it with a slow LFO on the cutoff. Play a minor chord.
```

Ask for the tedious things you'd never do by hand:

```text
Write six clips at 3, 5, 7, 11, 13 and 17 bar lengths. They're coprime,
so the loop won't repeat for over a million bars.
```

```text
Draw a twelve minute filter sweep with 200 automation points, then put
per-note probability on the hats so they flicker instead of repeating.
```

Ask it to fix what you just heard:

```text
The bass is too quiet and the reverb is too wet. Pull them back.
```

## How it works

The assistant talks to Ableton through the [Model Context Protocol](https://modelcontextprotocol.io) (MCP), an open standard for giving AI tools access to external systems. This project is an MCP server that exposes Ableton's Live Object Model as a set of tools the assistant can call.

There are two pieces:

The MCP server runs on your machine as its own process. Your AI client (Claude Code, Claude Desktop, Cursor) launches it and calls its tools.

A remote script runs inside Ableton itself. Ableton's Control Surface system lets you run Python inside Live, and that script opens a local socket the MCP server talks to. This is the only supported way into Live's API, so it has to be Python and it has to be enabled in Ableton's settings.

When you ask for something, the assistant calls a tool, the server sends a command over the socket, the remote script runs it against Live's API, and the result comes back. You see it happen in Ableton in real time.

## Installation

You need Ableton Live 11 or newer, and [uv](https://docs.astral.sh/uv/).

First, install the remote script into Live. This is the part that runs inside Ableton:

```bash
uvx --from ableton-ai install-remote-script
```

Then connect your AI client.

For Claude Code:

```bash
claude mcp add ableton -s user -- uvx ableton-ai
```

For Claude Desktop, add this to `claude_desktop_config.json` (find it under Settings, Developer, Edit Config):

```json
{
  "mcpServers": {
    "ableton": {
      "command": "uvx",
      "args": ["ableton-ai"]
    }
  }
}
```

Restart your AI client after either one, so it picks up the new server.

Finally, turn the remote script on in Ableton. Open Settings, then Link, Tempo & MIDI. Under Control Surface, pick AbletonMCP. Leave Input and Output on None.

Ableton's status bar should flash `AbletonMCP: Listening for commands on port 9877`. If it doesn't, the remote script isn't installed, so rerun the first step and restart Live.

## Getting started

Open a Live set you don't mind messing up, then hand your assistant this:

```text
You're controlling my Ableton Live set. You can't hear anything you make,
so don't tell me it sounds good. Build what I ask, read the settings back
to check they landed, and let me be the judge.

Some things in Live are dropdowns you can't set through the API: the LFO
Map button, a Compressor's sidechain source, Drift's mod matrix routing.
If you need one of those, tell me and I'll click it.

To start: make a MIDI track, load Drift, and build an ambient pad with a
slow attack and long release. Add a filter behind it with a slow LFO on
the cutoff. Play a minor chord and loop it.
```

That first paragraph is worth keeping around. It saves you re-explaining the same things every session. Better still, install the skill below, which teaches your assistant all of this and more.

## The skill

If you use Claude Code, there's a skill in `skills/ableton` that teaches the assistant how to use these tools well: the parameter names each command expects, how to verify a change actually landed, how to reach inside drum racks, and how to build generative patches with coprime loops and note probability.

Install it:

```bash
mkdir -p ~/.claude/skills
cp -R skills/ableton ~/.claude/skills/
```

Restart Claude Code. It picks the skill up whenever you ask for something musical.

## Editing the remote script

If you change the remote script, Ableton needs a restart to load it, because Live caches the compiled bytecode. Save your set, copy the updated file into place, and restart Live. Toggling the Control Surface off and on is not reliable.

## Safety

The remote script opens an unauthenticated socket on `localhost:9877`. It isn't reachable from the network, but any process running as you can drive Ableton through it.

The more practical point: the assistant has 130 commands that change your project, and it can't hear what it's doing. It will occasionally clear something you cared about. Work on copies, save often, and lean on Cmd+Z, which covers most operations.

## Testing

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests
uv run mypy
```

## Architecture

If you want to work on this, here's how the parts fit together. The earlier "How it works" section is the short version; this is the longer one.

There are two processes, and they don't share memory. The first is the MCP server, a normal Python package under `src/ableton_ai`. The second is the remote script under `remote_script`, which runs inside Ableton's own embedded Python interpreter. They talk to each other over a TCP socket on `localhost:9877`, passing JSON back and forth. That socket is the whole interface between them.

The MCP server is the side your AI client talks to. `server.py` builds a [FastMCP](https://modelcontextprotocol.io) server and registers every tool. The tools live in `src/ableton_ai/tools`, split by what they touch: `tracks`, `clips`, `notes`, `devices`, `browser`, `automation`, `arrangement`, `session`, and a few musical helpers. Each tool is a small function decorated with `@tool`, which registers it and wraps it in uniform error handling, so a tool body is usually two lines: send a command, format the result. None of the tools hold state. They all go through one shared `AbletonConnection` in `connection.py`, which owns the socket and serializes every exchange behind a lock, because the socket handles one command at a time.

The remote script is the side that can actually touch Live. Ableton's Control Surface system is the only supported way to run code inside Live and reach its API, and it only runs Python, which is why this half is Python no matter what. When Live loads the script, it opens the socket and waits. A command comes in as JSON, the script looks it up, runs it against Live's API, and sends the result back.

The one subtlety worth knowing is threading. The socket runs on a background thread, but Live's API can only be touched safely from Live's main thread. So any command that changes something (creating a track, setting a parameter, writing notes) is put on a queue and run on the main thread, while read-only commands can answer straight from the socket thread. This isn't decoration. A state change made from the wrong thread crashes Live outright, which is a mistake this codebase has made and fixed.

A single request, end to end: you ask for a track, the assistant calls the `create_midi_track` tool, the server sends `{"type": "create_midi_track", ...}` over the socket, the remote script queues it onto Live's main thread, Live makes the track, the result travels back through the socket to the tool, and the tool returns a sentence the assistant reads. You see the track appear in Ableton as it happens.

The last piece is `rest_api`, an optional HTTP server that exposes the same commands to clients that don't speak MCP, like a local Ollama model. It's not needed for the Claude workflow and you can ignore it unless you want it.

## Credits

Built on the original AbletonMCP by [Siddharth Ahuja](https://github.com/ahujasid) and later work by [Jason Poindexter](https://github.com/jpoindexter), with thanks to [calclavia](https://github.com/calclavia) and [Ronbalt](https://github.com/Ronbalt).

## License

MIT. See [LICENSE](LICENSE).
