# CoMPhy Lab logos, links, and QR codes

This repository is the public, reproducible source for CoMPhy Lab QR artwork,
useful links, and downloadable logo files. Its privacy-filtered inventory covers
71 codes: 69 observed in the source account plus two added public static
codes, comprising 14 active dynamic codes, four paused dynamic codes, and 53
static codes. Private targets are counted but redacted.

Browse the [download catalogue](https://comphy-lab.org/qr-codes/) for SVG
and PNG copies of all 65 public, non-paused account codes and the lab and
university logos. The four [standalone branded codes](current/) also include
SVG and PNG.

The contact-card replacement is
[`https://comphy-lab.org/contact-card/`](https://comphy-lab.org/contact-card/),
which supersedes the third-party dynamic code `https://qrco.de/beQCcR`.

## Catalogue

The catalogue follows the public CoMPhy Lab site: **Team**, **Research**,
**Teaching**, **Blog**, then **Logos**. PhD thesis material appears under
Research. Empty site sections, including Join Us, are omitted. These groups
organize the catalogue without changing any destination URL or QR payload. New
navigation uses `#team`, `#research`, `#teaching`, `#blog`, and `#logos`; the
former `#link-pages` and `#direct-codes` bookmarks remain as anchor aliases.

Four logo variants retain their original base filenames under `assets/logos/`:

- CoMPhy Lab: `CoMPhy-lab/CoMPhy-Lab`
- CoMPhy Lab mark: `CoMPhy-lab/CoMPhy-Lab-no-name`
- Durham University: `Durham/Durham-University`
- Durham University mark: `Durham/Durham-University_NoText`

Every variant is available as PNG and PDF; SVG is included where an original
SVG is available. The generator copies these files unchanged to
`site/assets/logos/`.

## Repository layout

- `inventory/codes.json`: authoritative, privacy-filtered account inventory.
- `scripts/`: inventory validation, deterministic generation, and deployment
  checks.
- `requirements-lock.txt`: complete, hashed Python dependencies.
- `current/account/`: generated replacements for public account codes.
- `current/`: standalone branded QR codes in SVG and PNG.
- `assets/logos/`: original downloadable logo files.
- `site/`: generated catalogue, landing pages, QR artwork, and logo downloads.
- `legacy/`: preserved historic SVG artwork.
- `DESIGN.md`: QR design and migration rules.

## Rebuild and verify

```bash
python3 -m pip install --require-hashes -r requirements-lock.txt
python3 scripts/validate_inventory.py
python3 scripts/generate.py --check
python3 -m unittest discover -v
```

Run `python3 scripts/generate.py` after changing the inventory or generated
catalogue. Do not hand-edit `current/account/` or `site/`. The standalone
branded-code generator needs `rsvg-convert` for PNG and PDF derivatives; it
uses `assets/comphy-lab-mark.png` by default and accepts `COMPHY_QR_MARK` as a
portable override.

GitHub Actions validates the inventory, generated files, and decoded QR
payloads before uploading `site/` unchanged to GitHub Pages. It then compares
the live pages and downloads with the validated source. Run
`python3 scripts/verify_deployment.py` to repeat the live check. The generated
HTML remains script-free and uses a restrictive content security policy.

The `bursting-bubble-paper` entry points to the 2021 viscoplastic paper. The
`arxiv-bursting-bubbles-ve` entry points directly to the 2025 viscoelastic
paper at `https://arxiv.org/pdf/2408.05089`. The
`arxiv-singularities-soft-matter` entry points directly to
`https://arxiv.org/pdf/2608.11060`.

## Publishing and migration

The repository is `comphy-lab/qr-codes`, and the catalogue is published at
`https://comphy-lab.org/qr-codes/`. Both were renamed from `port-qr-codes`.
Pages deploys through a custom Actions workflow, so a `CNAME` file
is neither created nor required; GitHub documents this behaviour in its
[custom-domain guidance](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).

For a future repository rename, update repository remotes, project manifests,
workflow references, generated base paths, and canonical URLs, then redeploy
and verify the site. GitHub redirects most repository traffic after a rename,
but excludes Pages project-site URLs; see its
[repository-renaming guidance](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).

External destinations are unchanged. The 14 QR codes that used
`https://comphy-lab.org/port-qr-codes/` now encode the corresponding
`https://comphy-lab.org/qr-codes/` routes. Replace artwork that encodes the old
path; GitHub does not provide a redirect for the old Pages URLs.
An already printed dynamic code still contains its old payload, so publishing a
replacement cannot alter the printed image. Replace former
`qr.comphy-lab.org` artwork with the corresponding files under
`current/account/`. The four paused codes remain historical entries without
replacement artwork, the two private static codes remain redacted, and
`legacy/` remains the evidence archive. Use `current/` for new artwork.
