// Downloads files queued by the "Send ... to Browser" nodes into this browser's Downloads folder.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const inFlight = new Set();

async function fetchAndSave(item) {
  if (inFlight.has(item.id)) return;
  inFlight.add(item.id);
  try {
    const res = await api.fetchApi(`/deliver/file/${item.id}`, { cache: "no-store" });
    if (!res.ok) return; // already taken by another tab, or expired
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = item.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    app.extensionManager?.toast?.add({ severity: "success", summary: "Downloaded", detail: item.name, life: 4000 });
  } catch (e) {
    console.error("[deliver] download failed", item, e);
  } finally {
    inFlight.delete(item.id);
  }
}

async function collectPending() {
  try {
    const res = await api.fetchApi("/deliver/pending", { cache: "no-store" });
    if (res.ok) for (const item of await res.json()) await fetchAndSave(item);
  } catch (e) {
    console.error("[deliver] pending check failed", e);
  }
}

app.registerExtension({
  name: "local.deliverToBrowser",
  setup() {
    api.addEventListener("deliver.ready", (e) => fetchAndSave(e.detail));
    api.addEventListener("reconnected", collectPending);
    collectPending();
  },
});
