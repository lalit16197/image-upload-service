const api = "/api/v1/images";
const partSize = 8 * 1024 * 1024;
const uploadConcurrency = 6;
const maxPartRetries = 3;
const $ = (id) => document.getElementById(id);

function message(element, text, error = false) {
  element.textContent = text;
  element.className = `status${error ? " error" : ""}`;
}

async function jsonRequest(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`);
  return body;
}

async function upload(event) {
  event.preventDefault();
  const form = event.target;
  const file = $("file").files[0];
  const button = form.querySelector("button");
  if (!file) return;
  button.disabled = true;
  message($("upload-status"), "Creating multipart upload...");
  try {
    const totalParts = Math.max(1, Math.ceil(file.size / partSize));
    const fields = new FormData(form);
    const initiated = await jsonRequest(`${api}/upload-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        owner_id: fields.get("owner_id"),
        file_name: file.name,
        content_type: file.type || "application/octet-stream",
        category: fields.get("category"),
        tag: fields.get("tag") || null,
        caption: fields.get("caption") || null,
        total_parts: totalParts
      })
    });
    const parts = await uploadParts(file, initiated.part_urls);
    await jsonRequest(`${api}/upload-complete`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ s3_key: initiated.s3_key, upload_id: initiated.upload_id, parts })
    });
    message($("upload-status"), "Upload completed. Validation and indexing are processing asynchronously.");
    form.reset();
    await loadImages();
  } catch (error) {
    message($("upload-status"), error.message, true);
  } finally {
    button.disabled = false;
  }

  async function uploadParts(file, partUrls) {
    const completed = new Array(partUrls.length);
    let nextIndex = 0;
    let finished = 0;

    async function worker() {
      while (true) {
        const index = nextIndex++;
        if (index >= partUrls.length) return;

        const start = index * partSize;
        const blob = file.slice(start, Math.min(start + partSize, file.size));
        completed[index] = {
          PartNumber: partUrls[index].part_number,
          ETag: await uploadPartWithRetry(partUrls[index].upload_url, blob, index + 1)
        };
        finished++;
        message($("upload-status"), `Uploaded ${finished} of ${partUrls.length} parts...`);
      }
    }

    const workers = Array.from(
      { length: Math.min(uploadConcurrency, partUrls.length) },
      () => worker()
    );
    await Promise.all(workers);
    return completed;
  }

  async function uploadPartWithRetry(url, blob, partNumber) {
    for (let attempt = 0; attempt <= maxPartRetries; attempt++) {
      try {
        const response = await fetch(url, { method: "PUT", body: blob });
        if (!response.ok) throw new Error(`S3 rejected part ${partNumber}`);

        const etag = response.headers.get("ETag");
        if (!etag) throw new Error(`S3 did not return an ETag for part ${partNumber}`);
        return etag.replaceAll('"', "");
      } catch (error) {
        if (attempt === maxPartRetries) throw error;
        await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
      }
    }
  }
}

async function loadImages(event) {
  if (event) event.preventDefault();
  const params = new URLSearchParams();
  for (const [key, value] of new FormData($("filter-form"))) if (value) params.set(key, value);
  if (![...params].some(([key]) => ["owner_id", "category", "tag"].includes(key))) {
    message($("list-status"), "Enter an owner, category, or tag filter.", true);
    return;
  }
  message($("list-status"), "Loading...");
  try {
    const images = await jsonRequest(`${api}?${params}`);
    $("images").innerHTML = images.length ? images.map(renderImage).join("") : '<p class="muted">No active images found.</p>';
    message($("list-status"), `${images.length} image(s) found.`);
  } catch (error) { message($("list-status"), error.message, true); }
}

function renderImage(image) {
  return `<article class="image-row">
    <div><strong>${escapeHtml(image.filename || image.image_id)}</strong>
    <small>${escapeHtml(image.owner_id)} · ${escapeHtml(image.category)} · ${escapeHtml(image.tag || "untagged")} · ${formatBytes(image.size_bytes)}</small></div>
    <div class="actions"><button onclick="downloadImage('${encodeURIComponent(image.owner_id)}','${encodeURIComponent(image.image_id)}')">View / download</button>
    <button class="danger" onclick="deleteImage('${encodeURIComponent(image.owner_id)}','${encodeURIComponent(image.image_id)}')">Delete</button></div>
  </article>`;
}

async function downloadImage(owner, image) {
  try { const result = await jsonRequest(`${api}/${owner}/${image}/download`); window.open(result.download_url, "_blank", "noopener"); }
  catch (error) { message($("list-status"), error.message, true); }
}

async function deleteImage(owner, image) {
  if (!confirm("Mark this image for deletion?")) return;
  try { await jsonRequest(`${api}/${owner}/${image}`, { method: "DELETE" }); message($("list-status"), "Deletion queued."); await loadImages(); }
  catch (error) { message($("list-status"), error.message, true); }
}

function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char])); }
function formatBytes(bytes) { if (!bytes) return "size pending"; const units = ["B", "KB", "MB", "GB"]; const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3); return `${(bytes / 1024 ** index).toFixed(1)} ${units[index]}`; }

$("upload-form").addEventListener("submit", upload);
$("filter-form").addEventListener("submit", loadImages);
$("refresh").addEventListener("click", loadImages);
