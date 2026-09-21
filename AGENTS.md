# qr-codes

## Purpose

Public, reproducible custody for CoMPhy Lab QR-code artwork and its migration
away from third-party dynamic QR services.

## Handling

- Commit SVG sources and `DESIGN.md` records. Generated PNG/PDF derivatives
  are allowed when they are useful for print or publication workflows.
- `inventory/codes.json` is the public migration authority. It contains one
  entry for every account code; private entries use opaque placeholders, while
  their exact IDs, names, folders, destinations, and artwork remain outside
  this repository.
- Generate `current/account/` and `site/` from the inventory. Do not hand-edit
  generated files or treat a rendered QR image as stronger evidence than its
  manifest payload. Add a new QR by adding one public, non-paused inventory
  entry and running the generator; that writes `current/account/{slug}.{svg,png,pdf}`
  and `site/{slug}/index.html` with no hand-authored HTML.
- Each active dynamic replacement must use a durable first-party URL. Existing
  static codes may retain a validated canonical destination. In both cases,
  decode the rendered SVG before it replaces live artwork.
- `legacy/` is an evidence archive, not proof that every historical target is
  still desirable or live. Do not silently redirect or retire a code.
- Do not add scans, customer/account metadata, signed vendor URLs, private
  contact details, analytics credentials, or unpublished destinations to this
  public repository.
- A generated first-party route is only deployment-ready source. Do not call it
  live until the deployed URL has been fetched and the returned page verified.
