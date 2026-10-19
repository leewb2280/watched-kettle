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
| `backdrop` | A list of layers drawn below the bubble surface (up to 8) |
| `overlay` | A list of layers drawn above the bubble surface (up to 8) |

A layer is drawn `x` and `y` away from its `anchor` (the body's `top-left`, `top-center`, `top-right`, `center-left`, `center-right`, `bottom-left`,
`bottom-center` or `bottom-right`, or `arc-top-left`, the 45° point of the rounded top-left corner). An image layer uses `image` (a PNG or WebP inside the package, 4 MB or less), `width` and `height`,
and can be flipped horizontally with `mirror`. With `tint`, the image is treated as a shape mask and filled with that color.
A dot layer is `circle: {"radius", "color"}`. A color is `#rrggbb` or a theme color name (`border`, `shadow`,
`background`, `text`); with a theme color name, the decoration's color follows when the user changes the bubble colors.
`alpha` is 0–255. While running, malformed layers are not drawn, and values are clamped to the allowed ranges.
If an image points outside the package or does not exist, the Windows build fails.

When adding a new format, existing versions must be detected automatically, and invalid fields must either fall back to
safe defaults or produce a clear load error. Public builds include only `distribution=public`
assets.

## Installing from the user folder

If you copy a complete pet directory to the user pets folder, the existing loader reads `pet.json`, the sprite and
the decoration images declared in `bubbleTheme.frame`. Prepare the whole folder, then refresh the
list or restart the app. This is separate from importing a single PNG/WebP image.
