# Overlays — local documents on top of the generic corpus

`kb_synthetic/` is the **generic** farm corpus: it says "the Farm", carries no
jurisdiction, and serves any operation. Local rules (a food-safety authority's
requirements, a buyer's specification, a water-discharge permit) never go
there — they go in an overlay here.

## Contract

```
kb_market/<name>/
  README.md         where the documents come from and who maintains them
  *.md              documents (same front matter + numbered sections as the corpus)
  citations.yaml    citation keys for those documents only
```

- Overlays are enabled in `profile.yaml`:

  ```yaml
  market:
    kb_overlays: [my-overlay]     # [] = generic corpus only
  ```

- A document whose front matter carries a **`status:`** line is a SKELETON: the
  build skips it, and skips its citation keys with it. Delete the `status:`
  line when the real text lands, then rebuild — that is the whole switch.
- Overlay chunks carry `meta["market"] = "<name>"`; generic chunks carry `""`,
  so retrieval and the UI can tell a local rule from house procedure.
- Overlay documents are **not** required to be synthetic. `synthetic: false`
  marks a real, public text; the generic-corpus tests do not apply to it.
- Templating is the same as the corpus (`{{currency}}`, `{{farm_en}}`,
  `{{farm_ar}}`), so an overlay can quote the profile's values.

`_template/` is an empty overlay to copy.

## Why

The same app must run for another farm in another country by swapping
`profile.yaml`. Anything that would be wrong somewhere else belongs in an
overlay, not in `kb_synthetic/`.
