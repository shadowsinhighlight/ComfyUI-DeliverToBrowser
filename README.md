# ComfyUI-DeliverToBrowser

Two output nodes that send results straight to your browser's Downloads folder and
**never write them to the ComfyUI machine's disk**. Built for a shared PC where
generated images and videos must not be stored.

| Node | Category | Does |
|---|---|---|
| **Send Image to Browser (no disk)** (`SendImageToBrowser`) | image | Encodes each image as PNG in RAM |
| **Send Video to Browser (no disk)** (`SendVideoToBrowser`) | video | Encodes the video as H.264 MP4 in RAM (`crf` sets quality, lower = better/larger) |

Use them instead of Save Image / Save Video / Preview Image, which write to
`output\` or `temp\`.

## How it works

1. The node encodes the file in memory and puts it in an in-memory queue, then tells
   the browser over ComfyUI's websocket (`deliver.ready`).
2. `web/deliver.js` (loaded automatically by ComfyUI) fetches it once from
   `/deliver/file/<id>` and saves it through a normal browser download, with a
   "Downloaded" toast.
3. The server drops the file as soon as it has been fetched. A second fetch gets 404.

If no browser tab is open, files wait in RAM for up to 2 hours (6 GB total, oldest
dropped first) and download the next time you open ComfyUI or the websocket
reconnects (`/deliver/pending`). They are lost if ComfyUI restarts before then.

## Options

- `filename_prefix`: start of the file name; a timestamp is added
  (`Krea2_20261118_171117.png`, `_000`, `_001` ... for batches).
- `embed_workflow` (default on): stores the prompt and workflow in the PNG text
  chunks / MP4 metadata, so the file can be dragged back into ComfyUI. Turn it off to
  strip it. ComfyUI's `--disable-metadata` flag also turns it off.

## Browser settings

- Allow multiple downloads once per site: Chrome shows an "Allow" bar the first time;
  in Safari, Settings > Websites > Downloads > Allow.
- Turn off "ask where to save each file", or every image opens a save dialog.

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart ComfyUI. No extra Python
packages (uses numpy, Pillow and aiohttp, which ComfyUI already has).

## Notes

- The download routes are ordinary ComfyUI routes. On a ComfyUI reachable from the
  network, put it behind a login, or
  anyone who can reach the server can collect pending files.
- Only images/videos produced by these two nodes are kept off disk. Files you upload
  with Load Image are still stored in `ComfyUI/input`.
