# QR-code design and migration ledger

## Design rules

- Authoritative artwork is SVG with a quiet zone retained around the code.
- Purple `#67236C` on white is the current CoMPhy treatment for QR modules.
  This artwork ink is deliberately separate from the site's brand purple
  `#68236D`; changing one must not silently change the other.
- A logo may only occupy the error-correction budget; every rendered variant
  must be decoded before publication.
- Public first-party destinations are preferred. A short redirect is allowed
  only when its destination is documented here and controlled by CoMPhy Lab.

## Known migration

| Legacy code | Replacement | Status |
| --- | --- | --- |
| `https://qrco.de/beQCcR` | `https://comphy-lab.org/contact-card/` | Replaced; the destination offers the contact card and vCard download. |

## Migration states

- `replacement-ready`: a public active dynamic code has a reviewed replacement
  payload and generated artwork. First-party pages still need a deployment
  receipt before physical cutover.
- `direct-static`: the original code already has a clear public destination;
  the replacement encodes that destination directly.
- `source-preserved`: a paused code or obsolete event asset is retained as
  evidence but is not promoted as a live destination.
- `private-redacted`: the account entry is counted, but its destination and
  artwork remain outside this public repository.

Every active dynamic replacement uses
`https://comphy-lab.org/qr-codes/<slug>/` as its stable payload.
These static, script-free pages preserve the
ability to update a destination without depending on a paid QR provider; all
outbound links must be explicit HTTPS URLs. Existing static codes continue to
encode their canonical destinations directly.

Each public, non-paused account code is distributed as a matching SVG, PNG,
and vector PDF. The PDF is a single square page of the same module runs as the
SVG, at 12 points per module, written by `scripts/generate.py` without an
extra PDF package. `resvg-py` remains the SVG rasterizer used by the decoder
tests; it does not emit PDF. Every such code also has a landing page at
`site/<slug>/index.html`, published as
`https://comphy-lab.org/qr-codes/<slug>/`, with the QR panel, SVG/PNG/PDF
downloads, and any documented outbound links. Those pages do not auto-redirect,
so the artwork stays downloadable. Direct-static codes still encode their
external URL; the landing page is where a person downloads that QR. The
download catalogue links each card title to that page and still offers the
three files directly. Bespoke branded artwork in `current/` also includes PNG
derivatives of its SVG sources.

## Page presentation

The generated pages are the only presentation surface, and `scripts/generate.py`
owns all of it; `site/` is build output and is never hand-edited.

- No JavaScript, no inline `<style>`, no `style` attribute, no cross-origin
  request. The page CSP is `default-src 'none'` with `img-src`, `style-src` and
  `font-src` at `'self'` only.
- Type is self-hosted from `assets/fonts/` under the SIL Open Font License
  (see `assets/fonts/OFL.txt`): Cormorant Garamond for the hero line, Fraunces
  for headings, IBM Plex Sans for body and UI, IBM Plex Mono for payloads.
- Colour, spacing, radius and motion follow the CoMPhy design-system tokens in
  both `prefers-color-scheme` states. Teal is the only interactive accent;
  purple is reserved for eyebrows, the brand mark, the hero gradient and the QR
  modules.
- The QR quiet zone is rendered on a white inner frame in both themes, so a
  camera can still resolve the code on a dark-mode phone.
- Every interactive target is at least 44 px tall, every generated `<ul>`
  restores `role="list"`, and every catalogue link carries an `aria-label`
  naming its code. There is no entrance animation; only hover and focus
  transitions, and those only where a fine pointer exists.

## Historical assets

`legacy/` retains the existing SVG collection in its original folder layout.
It is intentionally not a claim that the embedded targets are current. Each
asset gets a dedicated entry here after its payload, ownership, and current
destination have been verified.
