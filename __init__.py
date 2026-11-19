"""Deliver outputs straight to the browser - nothing is written to disk on this PC.

"Send Image to Browser" / "Send Video to Browser" encode PNG / MP4 in RAM and keep the bytes
in an in-memory queue. The web extension (web/deliver.js) downloads each file once over the
authenticated HTTPS session into the browser's Downloads folder; the server then drops it.
Files nobody fetched are kept in RAM for PENDING_TTL seconds (so a closed tab can collect
them when reopened) and are lost when ComfyUI restarts.
"""
import io
import json
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict

import numpy as np
from aiohttp import web
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from comfy.cli_args import args
from comfy_api.latest import Types
from server import PromptServer

PENDING_TTL = 2 * 3600            # seconds an unfetched file stays in RAM
PENDING_MAX_BYTES = 6 * 1024 ** 3  # evict oldest beyond this

_lock = threading.Lock()
_pending = OrderedDict()  # id -> {"name", "mime", "data", "created"}


def _prune():
    now = time.time()
    total = 0
    for k in list(_pending):
        if now - _pending[k]["created"] > PENDING_TTL:
            del _pending[k]
    for k in reversed(list(_pending)):
        total += len(_pending[k]["data"])
        if total > PENDING_MAX_BYTES:
            del _pending[k]


def _deliver(name, mime, data):
    fid = uuid.uuid4().hex
    with _lock:
        _pending[fid] = {"name": name, "mime": mime, "data": data, "created": time.time()}
        _prune()
    server = PromptServer.instance
    server.send_sync("deliver.ready", {"id": fid, "name": name, "size": len(data)}, server.client_id)
    logging.info("[deliver] queued %s (%.1f MB) for browser download", name, len(data) / 1e6)


def _base_name(prefix):
    prefix = re.sub(r"[^\w\-. ]+", "_", prefix).strip(" ._") or "ComfyUI"
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}"


def _metadata(prompt, extra_pnginfo):
    if args.disable_metadata:
        return None
    meta = dict(extra_pnginfo or {})
    if prompt is not None:
        meta["prompt"] = prompt
    return meta or None


class SendImageToBrowser:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "embed_workflow": ("BOOLEAN", {"default": True, "tooltip": "Store prompt + workflow in the PNG so it can be dragged back into ComfyUI."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "send"
    OUTPUT_NODE = True
    CATEGORY = "image"
    DESCRIPTION = "Downloads the images to the connected browser. Nothing is saved on the server."

    def send(self, images, filename_prefix, embed_workflow, prompt=None, extra_pnginfo=None):
        base = _base_name(filename_prefix)
        meta = _metadata(prompt, extra_pnginfo) if embed_workflow else None
        for i, image in enumerate(images):
            img = Image.fromarray(np.clip(255.0 * image.cpu().numpy(), 0, 255).astype(np.uint8))
            info = None
            if meta:
                info = PngInfo()
                for k, v in meta.items():
                    info.add_text(k, json.dumps(v))
            buf = io.BytesIO()
            img.save(buf, format="PNG", pnginfo=info, compress_level=4)
            _deliver(f"{base}_{i:03}.png" if len(images) > 1 else f"{base}.png", "image/png", buf.getvalue())
        return {"ui": {}}


class SendVideoToBrowser:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "embed_workflow": ("BOOLEAN", {"default": True, "tooltip": "Store prompt + workflow in the MP4 metadata."}),
                "crf": ("FLOAT", {"default": 18.0, "min": 0.0, "max": 51.0, "step": 1.0, "tooltip": "H.264 quality, lower = better/larger."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "send"
    OUTPUT_NODE = True
    CATEGORY = "video"
    DESCRIPTION = "Encodes the video to MP4 in memory and downloads it to the connected browser. Nothing is saved on the server."

    def send(self, video, filename_prefix, embed_workflow, crf, prompt=None, extra_pnginfo=None):
        buf = io.BytesIO()
        video.save_to(buf, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264,
                      metadata=_metadata(prompt, extra_pnginfo) if embed_workflow else None, crf=crf)
        _deliver(f"{_base_name(filename_prefix)}.mp4", "video/mp4", buf.getvalue())
        return {"ui": {}}


routes = PromptServer.instance.routes


@routes.get("/deliver/pending")
async def deliver_pending(request):
    with _lock:
        _prune()
        items = [{"id": k, "name": v["name"], "size": len(v["data"])} for k, v in _pending.items()]
    return web.json_response(items, headers={"Cache-Control": "no-store"})


@routes.get("/deliver/file/{fid}")
async def deliver_file(request):
    with _lock:
        item = _pending.pop(request.match_info["fid"], None)
    if item is None:
        return web.Response(status=404, text="Already delivered or expired")
    return web.Response(body=item["data"], content_type=item["mime"], headers={
        "Content-Disposition": f'attachment; filename="{item["name"]}"',
        "Cache-Control": "no-store",
    })


WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {"SendImageToBrowser": SendImageToBrowser, "SendVideoToBrowser": SendVideoToBrowser}
NODE_DISPLAY_NAME_MAPPINGS = {"SendImageToBrowser": "Send Image to Browser (no disk)", "SendVideoToBrowser": "Send Video to Browser (no disk)"}
