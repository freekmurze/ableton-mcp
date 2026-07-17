# AbletonMCP

Control Ableton Live from an AI assistant (Claude Code, Claude Desktop, Cursor, or any MCP client).

This is a fork. See [Credits](#credits) at the bottom for the full lineage. It adds per note probability and access to rack internals, and fixes a bug that crashed Live.

## What it can do

Create tracks, load instruments and effects from Live's browser, set any device parameter, write MIDI clips with per note probability, draw clip automation, control the mixer, and drive transport. Roughly 130 commands, covering most of the Live Object Model.

## What it cannot do

Worth reading before you start, because none of these are bugs and no amount of prompting gets around them.

**Anything that is a dropdown is unreachable.** Live does not expose routing choices as automatable parameters, so the API cannot touch them. In practice:

* The Max for Live LFO's **Map** button. Map it once by hand, after which the assistant owns every other knob on it (Rate, Depth, Jitter, Smooth).
* A Compressor's sidechain **Audio From** source. Everything else on the device is settable.
* Drift's **modulation matrix** source and destination selectors. The amounts are settable, the routing is not.

Rule of thumb: knobs are scriptable, dropdowns are yours.

**There is no "new set" command.** Use File, New Live Set yourself.

**The assistant cannot hear anything.** It can set a filter to 0.37 and verify the value took, but it has no idea what came out of your speakers. Treat it as a very fast pair of hands rather than a collaborator with taste. Every judgement about how something sounds has to be yours.

## Requirements

* Ableton Live 11 or newer (Live 12 recommended; note probability requires Live 11+)
* Python 3.10 or newer
* [uv](https://docs.astral.sh/uv/)

## Installation

### 1. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and install

```bash
git clone https://github.com/freekmurze/ableton-mcp.git
cd ableton-mcp
uv sync
```

> **Do not run `uvx ableton-mcp`.** That pulls a different package that happens to
> share the name on PyPI, not this fork. Install from your clone, as above.

### 3. Install the Remote Script into Live

**macOS**

```bash
mkdir -p ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonMCP
cp AbletonMCP_Remote_Script/__init__.py ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonMCP/
```

**Windows**

```powershell
mkdir "$env:USERPROFILE\Documents\Ableton\User Library\Remote Scripts\AbletonMCP"
copy AbletonMCP_Remote_Script\__init__.py "$env:USERPROFILE\Documents\Ableton\User Library\Remote Scripts\AbletonMCP\"
```

### 4. Enable it in Live

Open **Settings**, then **Link, Tempo & MIDI**. Under **Control Surface**, choose **AbletonMCP**. Leave Input and Output set to None.

Live's status bar should flash `AbletonMCP: Listening for commands on port 9877`. If it does not, the script did not load. Recheck step 3 and restart Live.

### 5. Connect your MCP client

**Claude Code**

```bash
claude mcp add ableton -s user -- uv run --directory /absolute/path/to/ableton-mcp ableton-mcp
```

**Claude Desktop or Cursor**

Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ableton": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/ableton-mcp", "ableton-mcp"]
    }
  }
}
```

Restart your MCP client afterwards. Clients read their config at startup, so a server added mid session will not appear until you restart.

### 6. Check it works

Open a **throwaway** Live set and ask your assistant to create a MIDI track and load an instrument. If a track appears, you are connected.

## Editing the Remote Script

Live loads remote scripts at startup and caches the compiled bytecode. After editing `__init__.py`:

1. Save your Live set.
2. Copy the file into the user library again.
3. Restart Live. Toggling the Control Surface off and on is unreliable, because Python caches the imported module.

If you add a command, register it in **three** places or it will silently fail with "Unknown command":

1. The `elif command_type in [...]` whitelist, if it modifies state.
2. A dispatch branch.
3. The handler method itself.

State modifying commands **must** run on Live's main thread, and that whitelist is what routes them there. A mutating command that skips it runs on the socket thread and **crashes Live**. That is precisely the bug fixed in this fork, so it is not hypothetical.

## Safety

The remote script opens an unauthenticated TCP socket on `localhost:9877`. It is not reachable from the network, but any process running as your user can drive Ableton through it.

More practically: an assistant with 130 commands can wreck a project quickly, and it cannot hear what it is doing. Work on copies, save often, and remember that Cmd+Z covers most API operations.

## What this fork changes

**New**

* `add_notes_with_probability`. Per note probability and velocity deviation, via Live 11+'s `MidiNoteSpecification`. The rest of the codebase uses the legacy `clip.set_notes()` 5 tuple API, which has no probability field at all.
* `set_chain_device_parameter` and `get_chain_device_parameters`. Reach devices nested inside racks, for example one drum pad's synth. Previously a rack exposed only its own (often unassigned) macros, leaving its contents unreachable.
* `set_song_scale` and `get_song_scale_names`. `get_song_scale` existed with no setter, so the global scale was readable but unchangeable.

**Fixed**

* **`load_browser_item_to_return` crashed Live.** It called `browser.load_item()` from the socket thread rather than the main thread, because it was missing from the main thread whitelist. Mutating Live off the main thread is a guaranteed crash. Now marshalled correctly.
* **Clip automation targeted the wrong device.** `set_clip_automation`, `get_clip_automation`, and `clear_clip_automation` matched a parameter by name across every device on a track and took the first hit. Names are shared constantly (Frequency exists on Auto Filter, Erosion, Reverb, and Grain Delay), so this silently automated whichever device happened to come first. They now accept `device_index`, and an ambiguous name raises rather than guessing.
* **`get_clip_automation` returned no curve.** It reported only `has_automation: true`, which made automation impossible to verify. It now samples the envelope with `value_at_time()` and returns the real shape.
* **`transpose_notes` destroyed probability.** It round tripped through `clip.set_notes()`, silently dropping every note's probability. It now uses the extended note API and preserves it.
* **Mixer commands failed silently.** `set_track_pan`, `set_track_volume`, and `set_send_level` defaulted a missing argument and reported success, so a wrong argument name would centre your pans or zero your sends while claiming it worked. They now raise.
* **`_clear_clip_automation` was defined twice.** Python kept the second, leaving the first as dead code. Removed.

**Improved**

* Device parameters now include `value_string`, the text Live prints on the knob ("Off", "1/16", "440 Hz"). Without it a caller sees a bare float and cannot tell what `Transpose Mode = 0.0` actually means.
* `get_scale_notes` defaults to the song's real scale instead of always assuming C major.

## Credits

**This is a fork.** It exists because of other people's work, and the interesting parts of the architecture are theirs.

* **[Siddharth Ahuja](https://github.com/ahujasid)**, author of the original [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp). The original concept, the socket based remote script, and the architecture everything here rests on.
* **[Jason Poindexter](https://github.com/jpoindexter)**, author of [jpoindexter/ableton-mcp](https://github.com/jpoindexter/ableton-mcp), the direct parent of this fork. Expanded the command surface enormously, added the REST API and the Max for Live device, and built the main thread marshalling that makes state changes safe in the first place.

Thanks also to the upstream contributors whose commits are part of this history: [calclavia](https://github.com/calclavia) and [Ronbalt](https://github.com/Ronbalt).

This fork's contribution is narrow: note probability, rack internals, and a handful of bug fixes found by using the thing in anger. The foundation is not mine.

Not affiliated with or endorsed by Ableton.

## Licence

MIT. See [LICENSE](LICENSE). The original copyright notice is retained, as MIT requires.
