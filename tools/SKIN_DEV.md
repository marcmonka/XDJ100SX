# XDJ-100SX Skin Development Guide

Context for Claude Code (via MCP) and human contributors working on the Mixxx skin.

---

## Overview

The skin runs on a **Raspberry Pi** connected to a **480×272 touchscreen** (landscape).
Mixxx renders the skin as a single-deck player — no second deck, no samplers, no vinyl control.

The skin files live in `mixxx/SKIN/XDJ100SX/`. Push changes with:

```bash
python3 tools/xdj-pi-dev.py --push        # push all files
python3 tools/xdj-pi-dev.py --push "*.qss" # push only QSS
python3 tools/xdj-pi-dev.py --screenshot   # see the result
```

Or use `--watch` to auto-push and screenshot on every save.

---

## File Structure

| File | Purpose |
|------|---------|
| `skin.xml` | Root — loads style.qss, sets minimum size, defines launch image |
| `config.xml` | Top-level layout: Day/Night toggle + deck area |
| `deck.xml` | Main deck template — info row, waveform, transport, performance panels |
| `deckminimal.xml` | Minimal deck view (collapsed state) |
| `tab.xml` | Reusable tab button template |
| `topbar.xml` | Top bar — BPM, pitch, track info |
| `waveform.xml` / `waveforms.xml` | Waveform display widgets |
| `overview.xml` | Track overview / position bar |
| `hotcues.xml` | Hot cue performance panel |
| `beatloop.xml` | Beat loop performance panel |
| `beatjump.xml` | Beat jump performance panel |
| `keyshift.xml` | Key shift performance panel |
| `stems.xml` | Stems performance panel |
| `beffect.xml` / `ceffectl.xml` / `ceffectr.xml` | Effect panels |
| `effects.xml` | Effects rack |
| `library.xml` | Library browser panel |
| `style.qss` | All QSS styling |

---

## Layout System

### Size syntax

```xml
<Size>WIDTH,HEIGHT</Size>
```

Suffixes:
- `f` — fixed (exact pixels, no stretch)
- `me` — minimum, expands
- `max` — maximum (won't grow beyond this)
- `min` — minimum (won't shrink below this)
- No suffix — exact fixed size

Examples:
```xml
<Size>65f,40f</Size>      <!-- 65×40, fixed -->
<Size>0me,65max</Size>    <!-- expands horizontally, max 65px tall -->
<Size>me,me</Size>        <!-- fills available space -->
```

### SizePolicy

```xml
<SizePolicy>me,me</SizePolicy>   <!-- preferred grow behavior -->
<SizePolicy>f,f</SizePolicy>     <!-- fixed -->
```

### Layout

```xml
<Layout>vertical</Layout>
<Layout>horizontal</Layout>
```

### WidgetStack

Shows one child at a time based on a ConfigKey value. Used for the performance panel tabs (hotcues, beatloop, etc.):

```xml
<WidgetStack>
  <Children>
    <WidgetGroup>...</WidgetGroup>  <!-- shown when stack index = 0 -->
    <WidgetGroup>...</WidgetGroup>  <!-- shown when stack index = 1 -->
  </Children>
</WidgetStack>
```

### Templates

Reusable XML fragments with variables:

```xml
<!-- Definition (tab.xml) -->
<Template>
  <PushButton>
    <ObjectName>TabButton<Variable name="tab_name"/></ObjectName>
    <Connection>
      <ConfigKey>[Tab],<Variable name="config_key"/></ConfigKey>
    </Connection>
  </PushButton>
</Template>

<!-- Usage -->
<Template src="skin:tab.xml">
  <SetVariable name="tab_name">HOT CUE</SetVariable>
  <SetVariable name="config_key">hotcue</SetVariable>
</Template>
```

---

## Widget Types

### PushButton

```xml
<PushButton>
  <ObjectName>MyButton</ObjectName>
  <Size>65f,40f</Size>
  <NumberStates>2</NumberStates>
  <State>
    <Number>0</Number>
    <Text>OFF</Text>
    <!-- <Pixmap>skin:/images/btn_off.png</Pixmap> -->
  </State>
  <State>
    <Number>1</Number>
    <Text>ON</Text>
  </State>
  <Connection>
    <ConfigKey>[Channel1],play</ConfigKey>
  </Connection>
</PushButton>
```

### Label

```xml
<Label>
  <ObjectName>TrackTitle</ObjectName>
  <Size>me,20f</Size>
  <Text>No Track</Text>
  <Connection>
    <ConfigKey>[Channel1],title</ConfigKey>
    <BindProperty>text</BindProperty>
  </Connection>
</Label>
```

### NumberLabel / NumberDisplay

For numeric values (BPM, pitch, time):

```xml
<NumberLabel>
  <ObjectName>BPM</ObjectName>
  <Size>60f,25f</Size>
  <Connection>
    <ConfigKey>[Channel1],bpm</ConfigKey>
  </Connection>
</NumberLabel>
```

### WaveformDisplay

```xml
<Visual>
  <ObjectName>Waveform</ObjectName>
  <Size>me,80f</Size>
  <Channel>1</Channel>
  <BgColor>#000</BgColor>
  <BgPixmap></BgPixmap>
  <EndOfTrackColor>#ff4444</EndOfTrackColor>
</Visual>
```

### Overview (track position bar)

```xml
<Overview>
  <ObjectName>TrackOverview</ObjectName>
  <Size>me,30f</Size>
  <Channel>1</Channel>
  <BgColor>#111</BgColor>
  <EndOfTrackColor>#ff0000</EndOfTrackColor>
</Overview>
```

### WidgetGroup (container)

```xml
<WidgetGroup>
  <ObjectName>MyGroup</ObjectName>
  <Layout>horizontal</Layout>
  <Size>me,40f</Size>
  <Children>
    <!-- child widgets here -->
  </Children>
</WidgetGroup>
```

---

## ConfigKeys

Format: `[Group],control`

### Deck controls (single deck — always Channel1)

| ConfigKey | Description |
|-----------|-------------|
| `[Channel1],play` | Play/pause toggle |
| `[Channel1],cue_default` | Cue button |
| `[Channel1],bpm` | Current BPM |
| `[Channel1],rate` | Pitch/rate slider |
| `[Channel1],volume` | Channel volume |
| `[Channel1],quantize` | Quantize on/off |
| `[Channel1],keylock` | Key lock on/off |
| `[Channel1],sync_enabled` | Sync on/off |
| `[Channel1],loop_enabled` | Loop active |
| `[Channel1],beatloop_size` | Current loop size |
| `[Channel1],hotcue_X_activate` | Trigger hot cue X |
| `[Channel1],hotcue_X_clear` | Clear hot cue X |
| `[Channel1],title` | Track title (text) |
| `[Channel1],artist` | Track artist (text) |
| `[Channel1],track_loaded` | 1 if track is loaded |

### Tab/panel switching (skin-internal)

The performance panels are driven by `[Channel2]` filter kill controls repurposed as tab flags — this is a hack to use existing bool ConfigKeys for panel visibility without needing Mixxx scripting:

```xml
<!-- Show hotcue panel when this is 1 -->
<Connection>
  <ConfigKey>[Channel2],filterLowKill</ConfigKey>
  <BindProperty>visible</BindProperty>
</Connection>
```

**Do not change this pattern** — it would require updating both skin XML and the MIDI mapping script.

### Skin-internal toggles

```xml
[Skin],daynight_toggle   <!-- Day/Night mode switch -->
```

---

## QSS Styling

Standard Qt stylesheet — subset of CSS. Applied via `style.qss`.

### What works

- `background-color`, `color`, `border`, `border-radius`
- `font-family`, `font-size`, `font-weight`
- `padding`, `margin`
- `min-width`, `max-width`, `min-height`, `max-height`
- `image: url(skin:/images/file.png)` — skin-relative paths
- State selectors: `WPushButton[value="1"]` — styling when button is active

### What does NOT work

- CSS Grid, Flexbox — not Qt
- CSS variables (`--my-var`) — not supported
- Animations / transitions
- `::before` / `::after` pseudo-elements
- `url()` with absolute paths — always use `skin:/` prefix for images
- `rgba()` with 4 args sometimes fails — test on device

### Object name targeting

```css
#MyButton { background: #333; }           /* by ObjectName */
WPushButton { border: 1px solid white; }  /* by widget type */
WPushButton[value="1"] { color: red; }    /* active state */
```

### Color palette (Pioneer style)

```
Play green:    #6ee128
Cue orange:    #eb870f
Slip red:      #d73535
Tab yellow:    #c3d541
Header dark:   #32323c
Title blue bg: #112f5c
Blue accent:   #2d85cd
Text white:    #e5e6ea
Background:    #000000
```

---

## Constraints & Rules

### Screen

- **Physical display**: 480×272px
- **Skin minimum**: 480×420 (Mixxx scales to fit, Pi display is rotated/scaled)
- Keep UI elements large enough to be finger-tappable (minimum ~40px touch targets)
- No horizontal scrolling — everything must fit in 480px width

### Single deck only

- Always use `[Channel1]` — never `[Channel2]`, `[Channel3]`, `[Channel4]` for actual controls
- `[Channel2]` filter kills are repurposed as panel tab visibility flags — don't use them for audio

### Performance panels

The skin has 5 performance panels (tabs): Hot Cue, Beat Loop, Beat Jump, Key Shift, Stems.
They are mutually exclusive (WidgetStack). Do not add a 6th tab without updating:
- The tab button row in `deck.xml`
- The WidgetStack in `deck.xml`
- The MIDI mapping in `XDJ100SX.midi.xml` and `XDJ100SX.js`

### Images

- Place in `mixxx/SKIN/XDJ100SX/images/`
- Reference as `skin:/images/filename.png`
- Keep image sizes minimal — Pi SD card and RAM are limited
- PNG preferred; avoid large JPEGs

### Templates

- Template files must start with `<Template>` as root element
- Variables are set with `<SetVariable name="...">value</SetVariable>`
- Used at call site with `<Template src="skin:file.xml">`

---

## Workflow with Claude Code MCP

When connected via MCP, Claude can:

```
"push the skin and take a screenshot"
"change the play button color to green in style.qss, push and screenshot"
"push only the hotcues.xml file"
"restart Mixxx then screenshot the beat loop panel"
"navigate to keyshift panel and screenshot"
```

Claude cannot:
- Modify Mixxx source code
- Change MIDI hardware behavior without updating both `.midi.xml` and `.js`
- Add new Mixxx controls that don't exist in the running Mixxx version
- Test interaction — only static screenshots are available via MCP
