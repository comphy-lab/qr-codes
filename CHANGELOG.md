# Changelog

## 2026-10-21

- Point the `vatsal-sanjay` QR payload at `https://comphy-lab.org/contact-card/`
  while keeping `/qr-codes/vatsal-sanjay/` as a normal download landing page
  with no redirect.

## 2026-09-08

- Renamed the repository from `comphy-lab/port-qr-codes` to
  `comphy-lab/qr-codes` and moved the site to
  `https://comphy-lab.org/qr-codes/`.
- Changed the catalogue headline to “Useful logos, links, and QR codes.”
- Organized entries as Team, Research, Teaching, and Blog, following the lab
  site, with PhD thesis material under Research and Logos last.
- Retained `#link-pages` and `#direct-codes` as aliases for existing catalogue
  bookmarks while moving navigation to the subject sections.
- Added four downloadable logo variants using their original filenames, with
  PNG and PDF for each and SVG where available.
- Renamed both sandbox entries to “Vatsal's Basilisk sandbox”.
- Removed route-status labels and explanatory route copy from catalogue cards
  and landing pages.
- Preserved external destinations and regenerated the 14 QR codes that use
  the renamed site routes. Retained the GitHub Actions Pages deployment.
- Allow PNG optimization to change invisible RGB values while verifying every
  visible pixel and alpha value.
