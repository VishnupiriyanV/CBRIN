# Caption fonts

ENGINE's brand kit offers three caption fonts by name (`Inter`, `Anton`, `Archivo Black` —
see `backend/brand_kit.py`'s `AVAILABLE_CAPTION_FONTS`), each under an open licence that
permits redistribution (SIL Open Font License). Their `.ttf`/`.otf` files are **not**
included in this repo — font binaries were not generated as part of this change, and
`caption_render.py` cannot manufacture them.

Before rendering captions with a real brand font, download and place here:

- `Inter-Bold.ttf` — https://github.com/rsms/inter (SIL OFL)
- `Anton-Regular.ttf` — https://fonts.google.com/specimen/Anton (SIL OFL)
- `ArchivoBlack-Regular.ttf` — https://fonts.google.com/specimen/Archivo+Black (SIL OFL)

Verify each font's licence permits redistribution before committing the binary
(ENGINE-PLAN.md risk #9).

Until a font file is present, `caption_render.py` falls back to Pillow's built-in bitmap
font and logs a warning — captions will render, just not in the chosen brand typeface.
