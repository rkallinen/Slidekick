/**
 * Slidekick API Client
 *
 * Centralised HTTP layer for all backend communication.
 */

import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// ── Slides ──────────────────────────────────────────────────────

export async function fetchSlides() {
  const { data } = await api.get("/slides/");
  return data;
}

export async function uploadSlide(file) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/slides/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120_000,
  });
  return data;
}

/**
 * Get the DZI XML URL for OpenSeadragon.
 * Note: returns the URL string, not the data.
 */
export function getDziUrl(slideId) {
  return `/api/slides/${slideId}/dzi`;
}

// ── Viewport nuclei (pre-computed from PostGIS) ─────────────────

export async function fetchViewportNuclei(slideId, bounds, level = 0) {
  const { data } = await api.post("/roi/nuclei", {
    slide_id: slideId,
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    level,
  });
  return data;
}

// ── Real-time inference on viewport (SSE streaming) ─────────────

/**
 * Inference with SSE progress streaming.
 * Returns { box, nuclei, count } on completion.
 */
export async function inferViewportWithProgress(slideId, bounds, level = 0, onProgress) {
  return new Promise((resolve, reject) => {
    fetch("/api/inference/viewport-stream", {
      method: "POST",
      headers: { 
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
      },
      body: JSON.stringify({
        slide_id: slideId,
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        level,
      }),
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.substring(6));
                
                if (data.type === "progress" && onProgress) {
                  onProgress(data);
                } else if (data.type === "complete") {
                  resolve(data);
                  return;
                } else if (data.type === "error") {
                  reject(new Error(data.message));
                  return;
                }
              } catch (e) {
                console.error("Failed to parse SSE data:", line, e);
              }
            }
          }
        }
      })
      .catch(reject);
  });
}

// ── Analysis Boxes ──────────────────────────────────────────────

export async function fetchAnalysisBoxes(slideId) {
  const { data } = await api.get(`/boxes/${slideId}`);
  return data;
}

export async function fetchAnalysisBoxDetail(boxId) {
  const { data } = await api.get(`/boxes/detail/${boxId}`);
  return data;
}

export async function deleteAnalysisBox(boxId) {
  await api.delete(`/boxes/${boxId}`);
}

export default api;
