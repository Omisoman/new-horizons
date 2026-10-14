# Overlay template

Copy this folder to `kb_market/<name>/`, add numbered markdown documents with
the corpus front matter (`title`, `synthetic`, and `status: skeleton` until the
real text lands), list their citation keys in `citations.yaml`, and switch the
overlay on in `profile.yaml -> market.kb_overlays`. Then `make kb`.
