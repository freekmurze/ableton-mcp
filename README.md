# Let AI control Ableton

Say "build me a dark ambient patch with a slow filter sweep" and watch your Live set fill in. New MIDI track, Drift loaded, slow attack, long release, Auto Filter behind it with an unsynced LFO drifting across the cutoff, a chord written at a 7 bar loop so it never quite lines up with anything else. Fired and playing. That takes about twenty seconds.

Then you listen, say the bass is too quiet, and it fixes that too.

That's the whole loop. You describe, it builds, you judge. Around 130 commands covering most of the Live Object Model: creating tracks, loading anything from your browser, turning any knob on any device, writing MIDI with per note probability, drawing automation, mixing, transport.

Where this gets genuinely interesting is the stuff you'd never do by hand because life is short. A twelve minute filter sweep with 200 breakpoints. Six parameters each on their own slow curve at different phase offsets. Clips at 3, 5, 7, 11, 13 and 17 bars, which are all coprime, so the full stack doesn't repeat for over a million bars. That's about 77 days of music that never plays the same way twice, and it took one sentence to ask for.

Per note probability is the other one. Every note gets its own chance of firing, so the kick stays certain while the hats flicker and the melody thins out and fills back in. Generative patches that actually evolve rather than loop.

None of that is hard. It's just tedious, and tedium is exactly what a machine should be doing while you get on with deciding whether any of it sounds good.

Let me walk you through it.

## What it can't do

I'm putting this near the top because these aren't bugs, and no amount of clever prompting gets around them. Better to know now than to spend an hour confused.

Anything that's a dropdown is unreachable. Live doesn't expose routing choices as automatable parameters, so the API can't touch them. That means the Map button on the Max for Live LFO, the Audio From selector on a Compressor's sidechain, and the source and destination selectors in Drift's modulation matrix. You set those by hand, once, and Claude owns every other knob on the device from then on. Knobs are scriptable, dropdowns are yours.

There's no command for a new Live set either. That's File, New Live Set, same as always.

The big one: Claude can't hear anything. It can set a filter to 0.37 and verify the value took, but it has no idea what came out of your speakers. It's a very fast pair of hands with no ears. Every judgement about whether something actually sounds good has to come from you. In my experience that's fine, and often better than it sounds, because the tedious part of music production isn't taste. It's typing 200 automation breakpoints.

## Installing

You'll need Ableton Live 11 or newer (12 is better, and note probability needs 11 as a minimum), Python 3.10 or newer, and [uv](https://docs.astral.sh/uv/).

First, install uv if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone this repo and install the dependencies:

```bash
git clone https://github.com/freekmurze/ableton-mcp.git
cd ableton-mcp
uv sync
```

Don't run `uvx ableton-mcp`. There's a different package with the same name on PyPI, and you'll silently install the wrong thing. Install from your clone.

Next, copy the remote script into Live's user library. On macOS:

```bash
mkdir -p ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonMCP
cp AbletonMCP_Remote_Script/__init__.py ~/Music/Ableton/User\ Library/Remote\ Scripts/AbletonMCP/
```

On Windows:

```powershell
mkdir "$env:USERPROFILE\Documents\Ableton\User Library\Remote Scripts\AbletonMCP"
copy AbletonMCP_Remote_Script\__init__.py "$env:USERPROFILE\Documents\Ableton\User Library\Remote Scripts\AbletonMCP\"
```

Now open Live, go to Settings, then Link, Tempo & MIDI. Under Control Surface, pick AbletonMCP. Leave Input and Output on None. Live's status bar should flash `AbletonMCP: Listening for commands on port 9877`. If it doesn't, the script didn't load, so check the path above and restart Live.

## Connecting Claude Code

One command:

```bash
claude mcp add ableton -s user -- uv run --directory /absolute/path/to/ableton-mcp ableton-mcp
```

Use the real absolute path to your clone. Then restart Claude Code, because it reads its MCP config at startup and a server added mid session won't show up until you do.

Check it worked:

```bash
claude mcp get ableton
```

You want to see `Status: ✔ Connected`.

## Connecting Claude Desktop

Open your config file. On macOS that's `~/Library/Application Support/Claude/claude_desktop_config.json`, and on Windows it's `%APPDATA%\Claude\claude_desktop_config.json`.

Add this:

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

Restart Claude Desktop. You should see a tools icon appear in the chat box.

## Your first prompt

Open a throwaway Live set, not something you care about. Then paste this in:

```text
You're driving my Ableton Live set through the AbletonMCP tools.

Before you build anything, read the current state with get_session_info and
get_track_info so you know what's already there.

Some things to keep in mind:

You can't hear anything you make. So don't tell me something sounds good.
Build it, verify the parameters actually took by reading them back, and let
me judge the sound.

Read a device's parameters with get_device_parameters before setting them.
Don't guess at parameter names or ranges. Every device is different, and the
value_string field tells you what Live actually prints on the knob.

Anything that's a dropdown in Live's UI can't be set through the API. That
includes the Max for Live LFO's Map button, a Compressor's sidechain source,
and Drift's mod matrix routing. If a plan needs one of those, tell me and
I'll click it.

Now: create a MIDI track, load Drift on it, and make an ambient pad with a
slow attack and a long release. Add an Auto Filter after it with a slow
unsynced LFO on the cutoff. Write a chord as a 7 bar loop and fire it.
```

That last paragraph is the actual request. Everything above it is context worth keeping around, so I'd suggest putting it in a `CLAUDE.md` in your project, or better, use the skill below.

## The skill

There's a skill in `skills/ableton` in this repo. It's a set of instructions that teaches Claude how to use these tools well: which parameter names each command actually wants, how to verify changes really landed, how to reach inside drum racks, and how to build generative patches with coprime loop lengths and note probability.

It exists because I made every one of those mistakes myself and got tired of explaining them again in each new session.

Install it by copying it into your skills folder:

```bash
mkdir -p ~/.claude/skills
cp -R skills/ableton ~/.claude/skills/
```

Restart Claude Code. Then type `/ableton` or just ask for something musical, and it'll pick the skill up on its own.

For Claude Desktop, skills live in your project or in the Capabilities settings, depending on your setup. Copying the folder to `~/.claude/skills` covers Claude Code.

## A warning worth reading

The remote script opens an unauthenticated TCP socket on `localhost:9877`. It isn't reachable from the network, but any process running as your user can drive Ableton through it.

The more realistic risk is Claude itself. It has 130 commands that change your project, and it can't hear what it's doing. It will occasionally clear an automation lane you cared about. Work on copies, save often, and lean on Cmd+Z, which covers most API operations.

## What's different here

I added per note probability through `add_notes_with_probability`, because the rest of the codebase uses Live's legacy `clip.set_notes()` API, and that one has no probability field at all. Probability is most of what makes a generative patch worth listening to, so this mattered.

I added `set_chain_device_parameter` and `get_chain_device_parameters` to reach devices nested inside racks. Before, a drum rack only handed you its own macros, which are usually unassigned, so a single drum pad's decay was untouchable.

`set_song_scale` and `get_song_scale_names` are new too. There was a getter for the song scale but no setter, which is a strange place to stop.

On the fixes: `load_browser_item_to_return` crashed Live outright. It called `browser.load_item()` from the socket thread instead of Live's main thread, and mutating Live off the main thread is a guaranteed crash. It took my Live down before I found it.

Clip automation used to target the wrong device. It matched a parameter by name across every device on the track and took the first hit, and names are shared constantly. Frequency exists on Auto Filter, Erosion, Reverb and Grain Delay. So you'd automate whichever device happened to come first and never know. It now takes a `device_index`, and an ambiguous name raises instead of guessing.

`get_clip_automation` never returned the curve, only `has_automation: true`, which made automation impossible to verify. It samples the envelope now and gives you the real shape.

`transpose_notes` silently destroyed probability by round tripping through the legacy API. `set_track_pan`, `set_track_volume` and `set_send_level` failed silently when you passed the wrong argument name, defaulting to a value and reporting success, which is how I once ran a whole session with every reverb send sitting at zero while being told it worked. And `_clear_clip_automation` was defined twice, so the first copy was dead code.

Device parameters now include `value_string`, the text Live prints on the knob. Without it you get a bare float and no idea what `Transpose Mode = 0.0` means.

## In closing

You can find the code [on GitHub](https://github.com/freekmurze/ableton-mcp). If something breaks, open an issue.

This is a fork, and the foundation isn't mine. [Siddharth Ahuja](https://github.com/ahujasid) wrote the [original](https://github.com/ahujasid/ableton-mcp): the concept, the socket based remote script, and the architecture all of this rests on. [Jason Poindexter](https://github.com/jpoindexter) built the [parent fork](https://github.com/jpoindexter/ableton-mcp), expanded the command surface enormously, added the REST API and the Max for Live device, and wrote the main thread marshalling that makes state changes safe in the first place. Thanks also to [calclavia](https://github.com/calclavia) and [Ronbalt](https://github.com/Ronbalt), whose commits are part of this history.

What I added is narrow: probability, rack internals, and a handful of bugs I found by using the thing in anger. Everything underneath is theirs.

It's MIT licensed, and not affiliated with Ableton.
