# Pet package format

[한국어](pet-package-format.md) · [English](pet-package-format.en.md)

Each pet is a self-contained directory that includes at least `pet.json` and `spritesheet.webp`.
For security, `spritesheetPath` cannot point outside the pet directory.

## Sprites

- V1: 1536×1872, 8 columns × 9 rows
- V2: 1536×2288, 8 columns × 11 rows
- Source frame: 192×208
- The nine basic states: idle, running-left, running-right, waving, jumping, failed,
  waiting, running, review
- The last two rows of V2 are frames for looking in 16 directions.

## Optional appearance changes (`appearanceSet`)

The base V1/V2 formats stay the same. An optional `appearanceSet` lets one V2 pet switch between looks.
The default look's path must equal the top-level `spritesheetPath`. Apps that do not know the extension
show only the default look.

Version 1 declares exactly two looks with Korean and English `labels` and both transitions. Version 2
(0.15.11 or newer) declares two to six looks. A look may use one plain `label` instead of `labels`;
language names fall back from the current language to English to the first name. `transitions` lists only
drawn pairs and may be empty: a pair drawn only in the other direction plays in reverse, and a pair with
neither cross-fades the two front idle frames for about 0.4 seconds. Optional `auto` sets automatic timing:
integer `minSeconds` and `maxSeconds` from 10 to 3600 (smaller first) and an `order` of `random` (any
other look) or `sequence` (declaration order). Without it the app uses 60–180 seconds at random. Users can
change the interval and order per pet.

```json
"appearanceSet": {
  "version": 2,
  "default": "day",
  "variants": [
    {"id": "day", "label": "Day", "spritesheetPath": "spritesheet.webp"},
    {"id": "night", "labels": {"ko": "밤", "en": "Night"}, "spritesheetPath": "appearance/night.webp"},
    {"id": "rain", "label": "Rain", "spritesheetPath": "appearance/rain.webp"}
  ],
  "transitions": [
    {"from": "day", "to": "night", "spritesheetPath": "appearance/day-night.webp", "frames": 12, "intervalMs": 60}
  ],
  "auto": {"minSeconds": 60, "maxSeconds": 180, "order": "sequence"}
}
```

Look IDs are 1–64 characters of lowercase letters, digits, underscores and hyphens starting with a letter;
`auto` is reserved. IDs and asset paths must be unique. Every look is a still 1536×2288 PNG/WebP with all
nine actions and sixteen look directions. A transition is a still image of same-sized cells laid out
horizontally: 2–32 frames in version 1, 2–48 in version 2, each 16–1000 ms. Each file may be up to 20 MiB,
and the package, path and link limits still apply. Folder and ZIP imports validate and normalize the
declaration and images and include them in the content identity. Appearance changes need 0.15.11 or newer;
older apps show only the default look.

## Main manifest fields

Besides still PNG/WebP images (20 MiB or less), **Import pet** in settings also accepts a ZIP, a pet folder, an install command and pets installed in Codex
(see [Other inputs and supported information](#other-inputs-and-supported-information) below). This section describes the basic path that verifies a single image and turns it
into a local package. The required cells of the nine basic states and all of the last two rows of V2 must contain artwork on a transparent background.
An `imported-<hash>` ID is made from the SHA-256 of the normalized RGBA size and pixels, and a lossless `spritesheet.webp` with metadata removed
and a `distribution: private` manifest are saved. The size is not changed.
An image with the same pixels reuses the existing package and does not overwrite it. Prepared data is kept in memory only, for at most one item and 10 minutes,
and discarded on cancel, a new selection, hiding the settings window or closing the connection. Only a completed directory is published to the list,
and web metadata or decorations are never guessed.

### Other inputs and supported information

The import window offers three inputs: file or folder, install command, and pets installed in Codex.
Files can be the existing PNG/WebP or a ZIP. For a folder, choose a package that contains pet.json.
A ZIP must contain one package at its root or inside a single wrapper folder, and must be 64 MiB or less,
with 64 files or fewer and a total uncompressed size of 96 MiB or less. Files are not actually extracted.
Path escapes, duplicate paths, links, junctions and encrypted ZIPs are rejected. The manifest must be 256 KiB or less,
the sprite 20 MiB or less, and each decoration image 4 MiB or less.

Supported: the name, description, per-language descriptions, the author and license if provided, the default size, look range, idle activities,
the bubble theme and frame decorations. `user:` asset references from another user's environment are not
copied, and excluded information is reported before registration. Decoration images are verified, normalized and kept as
PNG, and rewritten with paths inside the package. The original ID is never used to choose a local folder.
Existing image-only IDs stay as they are; if there are actions, a theme or decorations, `importedpkg-<hash>` is
used. The display name, description, author, license and source are excluded from the hash.
The name and settings of the same asset already registered are not overwritten. Imported pets are `distribution: private`.

`npx [-y|--yes] codexpetdb install <slug>` and `npx [-y|--yes] petscodex install <slug>`,
as well as the direct forms `petdb`, `codexpetdb` and `petscodex install <slug>`, are interpreted.
Only one command is accepted, and extra options, shell operators and arbitrary URLs are not supported. The command is never run.
For CodexPetDB, the discovery data, catalog, ZIP size and SHA-256 and the manifest ID are verified;
for Pets Codex, the manifest and the assets it references are read from a single commit of the public repository.
The network uses only fixed HTTPS sources and rejects redirects. Limits of 8 seconds to wait for a response and 120 seconds
in total apply, and you can cancel. If a service is unavailable, you can import with the file input instead.

The list of pets installed in Codex is read, read-only, from pets under CODEX_HOME or ~/.codex.
The list is read again on your request, and only folders with a server-issued item ID can be selected.
After selection an independent local copy is made, so deleting or changing the original does not affect the imported pet.
Network and package preparation run in a single worker, and canceled results cannot be registered.
A new preparation starts after the previous worker is cleaned up, and there are no automatic retries or automatic installs.

Action previews are offered only in the import window, showing the nine actions and V2's 16-direction poses.
They use the existing ANIMATIONS frame counts and intervals and pass only a PNG strip of at most 8 frames at a time.
The 4 MiB IPC limit is kept. With Reduce motion on, the preview starts paused.
Previewing or registering alone does not change the desktop pet, activity or notification state.

- `id`: a stable pet identifier
- `displayName`: the name shown to users
- `description`: an optional one-line description, used when there is no per-language description below
- `localizedDescriptions`: optional per-language descriptions, keyed by language code, such as
  `{"en": "...", "en-GB": "..."}`. The key that exactly matches the current language pack's language code is chosen first, then the same language (`en`), then `description`
- `spritesheetPath`: the sprite path inside the package
- `spriteVersionNumber`: 1 or 2
- `distribution`: public or private
- `defaultWidth`, `defaultLookRange`: optional default display settings
- `idleActivities`: an optional list of idle activities
- `bubbleTheme`: an optional bubble theme. Background photo, border image and sticker entries refer only to images the user imported (`user:` elements). Package images are used only through `frame` below

## Decorations outside the bubble (`bubbleTheme.frame`)

A pet's own bubble decorations are declared as data in `bubbleTheme.frame`. In a package with decorations, the theme's
`frame_style` becomes `pet:<id>`, and the app registers the decorations when it loads the pet. A package copied to the user
pets folder uses the same decorations. Values are pixels at 100% scale and grow with the bubble scale.

| Field | Meaning |
|---|---|
| `insets` | `[left, top, right, bottom]` margins to reserve outside the bubble body (0–120) |
| `contentPadding` | `[top, bottom, extra left]` padding inside the body |
| `innerBorder` | `color` and `alpha` of the inner line of a double border |
| `halo` | A halo around the body: `color`, `alpha`, `width`, `minWidth`, `offsetY`, `grow`, `radiusDelta` |
| `backdrop` | A list of layers drawn below the bubble surface (up to 16; 8 in 0.15.10 and older) |
| `overlay` | A list of layers drawn above the bubble surface (up to 16; 8 in 0.15.10 and older) |

A layer is drawn `x` and `y` away from its `anchor` (the body's `top-left`, `top-center`, `top-right`, `center-left`, `center-right`, `bottom-left`,
`bottom-center` or `bottom-right`, or `arc-top-left`, the 45° point of the rounded top-left corner). An image layer uses `image` (a PNG or WebP inside the package, 4 MB or less), `width` and `height`,
and can be flipped horizontally with `mirror`. With `tint`, the image is treated as a shape mask and filled with that color.
A dot layer is `circle: {"radius", "color"}`. A color is `#rrggbb` or a theme color name (`border`, `shadow`,
`background`, `text`); with a theme color name, the decoration's color follows when the user changes the bubble colors.
`alpha` is 0–255. While running, malformed layers are not drawn, and values are clamped to the allowed ranges.
If an image points outside the package or does not exist, the Windows build fails.

### Repeat images to fit the body height (0.15.10 or newer)

An image layer can declare `"repeatY": {"gap": 3, "bottomInset": 10}` to repeat downwards from its
existing `x` and `y`. Only `top-left`, `top-center` and `top-right` anchors support repetition.
`gap` is the space between copies and `bottomInset` reserves space above the body bottom.
Both default to 0 and accept finite numbers from 0 to 200. Image size, gaps and insets follow the bubble scale;
copies are never stretched to fill the available space. At most 256 whole copies fitting vertically inside the
body are painted, or none when there is no space. Only the repeated layer is clipped to the body rectangle;
existing decorations outside the body are unaffected.

Missing or invalid repeat settings, unsupported anchors and circle layers retain the existing single decoration.
Opacity, tint and horizontal mirroring apply to every copy. No new settings UI is required; live bubbles and
the existing preview share the painter. Folder and ZIP import preserve the options and image.
Older apps ignore this option, so distribution packs requiring repetition must set their minimum app version to 0.15.10 or newer.

### Rotation, vertical flip and horizontal repeat (0.15.11 or newer)

Image layers accept `rotation` (degrees from -180 to 180, around the image center) and `flipY` (vertical flip).
`"repeatX": {"gap": 2, "rightInset": 10}` repeats towards the body's right edge from `top-left`, `center-left`
and `bottom-left` anchors. Only the body's horizontal range is clipped, so rows above or below the body work too.
Other rules match `repeatY`. Older apps ignore these fields, so distribution packs using them must set their
minimum app version to 0.15.11 or newer.

User bubble themes have decoration layers (`decor`) with the same anchors and painter. A user layer names its
image as `user:<id>` (image library) or `pkg:<pet id>/<path inside the package>` and keeps the image's aspect
ratio inside its box.

When adding a new format, existing versions must be detected automatically, and invalid fields must either fall back to
safe defaults or produce a clear load error. Public builds include only `distribution=public`
assets.

## Installing from the user folder

If you copy a complete pet directory to the user pets folder, the existing loader reads `pet.json`, the sprite and
the decoration images declared in `bubbleTheme.frame`. Prepare the whole folder, then refresh the
list or restart the app. This is separate from importing a single PNG/WebP image.
