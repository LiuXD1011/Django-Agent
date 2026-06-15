function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return "";
}

async function md5Hex(file) {
  if (window.SparkMD5) {
    const buffer = await file.arrayBuffer();
    return SparkMD5.ArrayBuffer.hash(buffer);
  }
  return "";
}

async function digestHex(file) {
  const buffer = await file.arrayBuffer();
  const hash = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(hash)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function postForm(url, formData) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "X-CSRFToken": getCookie("csrftoken"),
      "Accept": "application/json",
      "X-Requested-With": "fetch",
    },
    body: formData,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.message || "请求失败");
  return data;
}

document.addEventListener("DOMContentLoaded", () => {
  initAvatarFallbacks();
  initDrivePage();
  initAutoSubmitForms();
  initAssistantPage();

  const assistantForm = document.querySelector("#assistant-form");
  if (assistantForm) {
    const assistantTextarea = assistantForm.querySelector("textarea[name='message']");
    assistantTextarea?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      assistantForm.requestSubmit();
    });
    assistantForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await streamForm(assistantForm, document.querySelector("#chat-history"), true);
    });
  }

});

function initAssistantPage() {
  const page = document.querySelector("[data-assistant-page]");
  if (!page) return;

  const form = document.querySelector("#assistant-form");
  const kbSelect = form?.querySelector("select[name='kb_id']");
  const deleteConfirm = page.querySelector("[data-delete-confirm]");
  const deleteConfirmSubmit = page.querySelector("[data-delete-confirm-submit]");
  let pendingDeleteUrl = "";

  function closeDeleteConfirm() {
    if (!deleteConfirm) return;
    deleteConfirm.hidden = true;
    pendingDeleteUrl = "";
  }

  function openDeleteConfirm(url) {
    if (!deleteConfirm) return;
    pendingDeleteUrl = url || "";
    deleteConfirm.hidden = false;
    deleteConfirmSubmit?.focus();
  }

  deleteConfirm?.querySelectorAll("[data-delete-cancel]").forEach((button) => {
    button.addEventListener("click", closeDeleteConfirm);
  });

  deleteConfirmSubmit?.addEventListener("click", async () => {
    if (!pendingDeleteUrl) return;
    deleteConfirmSubmit.disabled = true;
    try {
      const data = await postForm(pendingDeleteUrl, new FormData());
      window.location.href = data.next_url || "/assistant/";
    } finally {
      deleteConfirmSubmit.disabled = false;
      closeDeleteConfirm();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && deleteConfirm && !deleteConfirm.hidden) {
      closeDeleteConfirm();
    }
  });

  page.querySelector("[data-new-conversation]")?.addEventListener("click", async () => {
    const body = new FormData();
    if (kbSelect?.value) body.append("kb_id", kbSelect.value);
    const data = await postForm(page.dataset.createUrl, body);
    if (data.conversation?.url) window.location.href = data.conversation.url;
  });

  page.querySelector("[data-rename-conversation]")?.addEventListener("click", async (event) => {
    const active = page.querySelector(".assistant-conversation.active span");
    const title = prompt("新的对话标题", active?.textContent?.trim() || "");
    if (!title || !title.trim()) return;
    const body = new FormData();
    body.append("title", title.trim());
    const data = await postForm(event.currentTarget.dataset.url, body);
    if (active && data.conversation?.title) active.textContent = data.conversation.title;
  });

  page.querySelector("[data-delete-conversation]")?.addEventListener("click", async (event) => {
    openDeleteConfirm(event.currentTarget.dataset.url);
  });
}

function initAvatarFallbacks() {
  document.querySelectorAll(".user-avatar img").forEach((image) => {
    if (image.complete && image.naturalWidth === 0) {
      image.closest(".user-avatar")?.classList.add("avatar-broken");
      return;
    }
    image.addEventListener("error", () => {
      image.closest(".user-avatar")?.classList.add("avatar-broken");
    });
  });
}

function initAutoSubmitForms() {
  document.querySelectorAll("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", (event) => {
      if (event.target.matches("select")) form.requestSubmit();
    });
  });
}

function initDrivePage() {
  const drive = document.querySelector("[data-drive-page]");
  if (!drive) return;

  initModals();
  initFileActions(drive);
  initDriveUpload(drive);
}

function initModals() {
  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open-modal]");
    if (opener) openModal(opener.dataset.openModal);

    if (event.target.matches("[data-close-modal]")) {
      closeModal(event.target.closest(".file-modal"));
    }

    if (event.target.classList.contains("file-modal")) {
      closeModal(event.target);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".file-modal:not([hidden])").forEach(closeModal);
  });
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.hidden = false;
}

function closeModal(modal) {
  if (modal) modal.hidden = true;
}

function selectedFileIds() {
  return Array.from(document.querySelectorAll(".file-check:checked")).map((item) => item.value);
}

function setRepeatedHiddenInputs(container, name, values) {
  container.innerHTML = "";
  values.forEach((value) => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    container.appendChild(input);
  });
}

function initFileActions(drive) {
  const selectionBar = document.querySelector("#selection-bar");
  const selectionCount = document.querySelector("#selection-count");

  const updateSelection = () => {
    const ids = selectedFileIds();
    if (selectionBar) selectionBar.hidden = ids.length === 0;
    if (selectionCount) selectionCount.textContent = ids.length;
    const all = document.querySelector("#select-all-files");
    const checks = Array.from(document.querySelectorAll(".file-check"));
    if (all) {
      all.checked = checks.length > 0 && checks.every((item) => item.checked);
      all.indeterminate = checks.some((item) => item.checked) && !all.checked;
    }
  };

  drive.addEventListener("change", (event) => {
    if (event.target.matches("#select-all-files")) {
      document.querySelectorAll(".file-check").forEach((item) => {
        item.checked = event.target.checked;
      });
      updateSelection();
    }
    if (event.target.matches(".file-check")) updateSelection();
  });

  drive.addEventListener("click", (event) => {
    const renameButton = event.target.closest(".js-rename");
    if (renameButton) {
      const row = renameButton.closest(".file-row");
      const form = document.querySelector("#rename-form");
      const input = document.querySelector("#rename-input");
      form.action = row.dataset.renameUrl;
      input.value = row.dataset.fileName;
      openModal("rename-modal");
      input.focus();
      input.select();
      return;
    }

    const transferButton = event.target.closest(".js-transfer");
    if (transferButton) {
      const row = transferButton.closest(".file-row");
      openTransferModal({
        action: transferButton.dataset.action,
        formUrl: transferButton.dataset.action === "copy" ? row.dataset.copyUrl : row.dataset.moveUrl,
        itemIds: [],
        currentParentId: drive.dataset.currentParentId || "",
        description: row.dataset.fileName,
      });
      return;
    }

    const deleteButton = event.target.closest(".js-delete");
    if (deleteButton) {
      const row = deleteButton.closest(".file-row");
      openDeleteModal({
        formUrl: row.dataset.deleteUrl,
        itemIds: [],
        description: row.dataset.fileName,
      });
      return;
    }

    const bulkButton = event.target.closest(".js-bulk-action");
    if (bulkButton) {
      const ids = selectedFileIds();
      if (!ids.length) return alert("请选择文件");
      const action = bulkButton.dataset.action;
      if (action === "delete") {
        openDeleteModal({
          formUrl: drive.dataset.bulkDeleteUrl,
          itemIds: ids,
          description: `${ids.length} 个项目`,
        });
      } else {
        openTransferModal({
          action,
          formUrl: action === "copy" ? drive.dataset.bulkCopyUrl : drive.dataset.bulkMoveUrl,
          itemIds: ids,
          currentParentId: drive.dataset.currentParentId || "",
          description: `${ids.length} 个项目`,
        });
      }
    }
  });

  updateSelection();
}

function openTransferModal({ action, formUrl, itemIds, currentParentId, description }) {
  const form = document.querySelector("#transfer-form");
  const hidden = document.querySelector("#transfer-hidden-inputs");
  const title = document.querySelector("#transfer-title");
  const desc = document.querySelector("#transfer-desc");
  const submit = document.querySelector("#transfer-submit");
  const target = document.querySelector("#transfer-target");
  form.action = formUrl;
  setRepeatedHiddenInputs(hidden, "item_ids", itemIds);
  title.textContent = action === "copy" ? "复制到" : "移动到";
  submit.textContent = action === "copy" ? "确认复制" : "确认移动";
  desc.textContent = `为 ${description} 选择目标文件夹。`;
  target.value = currentParentId || "";
  openModal("transfer-modal");
}

function openDeleteModal({ formUrl, itemIds, description }) {
  const form = document.querySelector("#delete-form");
  const hidden = document.querySelector("#delete-hidden-inputs");
  const desc = document.querySelector("#delete-desc");
  form.action = formUrl;
  setRepeatedHiddenInputs(hidden, "item_ids", itemIds);
  desc.textContent = `${description} 将被移入回收站，之后仍可恢复。`;
  openModal("delete-modal");
}

function initDriveUpload() {
  const fileInput = document.querySelector("#upload-files");
  const browseButton = document.querySelector("#upload-browse");
  const dropzone = document.querySelector("#upload-dropzone");
  const queueNode = document.querySelector("#upload-queue");
  const startButton = document.querySelector("#upload-start");
  const parentSelect = document.querySelector("#upload-parent-id");
  if (!fileInput || !queueNode || !startButton || !parentSelect) return;

  const queue = [];

  const addFiles = (files) => {
    Array.from(files || []).forEach((file) => {
      const row = document.createElement("div");
      row.className = "upload-queue-row";
      row.innerHTML = `
        <div>
          <strong>${escapeHtml(file.name)}</strong>
          <small>等待上传 · ${formatBytes(file.size)}</small>
        </div>
        <span class="upload-percent">0%</span>
        <div class="upload-row-progress"><span></span></div>
      `;
      queueNode.appendChild(row);
      queue.push({ file, row, done: false });
    });
    startButton.disabled = queue.length === 0;
  };

  browseButton?.addEventListener("click", () => fileInput.click());
  dropzone?.addEventListener("click", (event) => {
    if (event.target === dropzone) fileInput.click();
  });
  fileInput.addEventListener("change", () => addFiles(fileInput.files));

  ["dragenter", "dragover"].forEach((name) => {
    dropzone?.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    dropzone?.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone?.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));

  startButton.addEventListener("click", async () => {
    if (!queue.length) return alert("请选择文件");
    startButton.disabled = true;
    const parentId = parentSelect.value || "";
    let failed = 0;
    for (const item of queue) {
      if (item.done) continue;
      try {
        await uploadOneFile(item, parentId);
        item.done = true;
      } catch (err) {
        failed += 1;
        setUploadProgress(item, 100, err.message, "error");
      }
    }
    if (failed === 0) {
      window.location.href = parentId ? `/files/?folder=${encodeURIComponent(parentId)}` : "/files/";
    } else {
      startButton.disabled = false;
    }
  });
}

function setUploadProgress(item, percent, text, state) {
  const width = Math.max(0, Math.min(100, Math.round(percent)));
  item.row.querySelector(".upload-row-progress span").style.width = `${width}%`;
  item.row.querySelector(".upload-percent").textContent = `${width}%`;
  item.row.querySelector("small").textContent = text;
  item.row.classList.toggle("done", state === "done");
  item.row.classList.toggle("error", state === "error");
}

async function uploadOneFile(item, parentId) {
  const file = item.file;
  setUploadProgress(item, 2, "计算文件指纹", "");
  const contentHash = await md5Hex(file);
  if (contentHash && await trySecondUpload(file, parentId, contentHash)) {
    setUploadProgress(item, 100, "秒传完成", "done");
    return;
  }

  const chunkThreshold = 8 * 1024 * 1024;
  if (file.size <= chunkThreshold) {
    await uploadPlainFile(file, parentId, contentHash, item);
    return;
  }
  await uploadChunkedFile(file, parentId, contentHash, item);
}

async function trySecondUpload(file, parentId, contentHash) {
  const body = new FormData();
  body.append("filename", file.name);
  body.append("content_hash", contentHash);
  body.append("parent_id", parentId || "");
  const response = await fetch("/files/upload/second/", {
    method: "POST",
    headers: {
      "X-CSRFToken": getCookie("csrftoken"),
      "Accept": "application/json",
      "X-Requested-With": "fetch",
    },
    body,
  });
  const data = await response.json();
  return response.ok && data.ok === true;
}

async function uploadPlainFile(file, parentId, contentHash, item) {
  const body = new FormData();
  body.append("file", file, file.name);
  body.append("parent_id", parentId || "");
  if (contentHash) body.append("content_hash", contentHash);
  setUploadProgress(item, 18, "上传中", "");
  await postForm("/files/upload/", body);
  setUploadProgress(item, 100, "上传完成", "done");
}

async function uploadChunkedFile(file, parentId, contentHash, item) {
  const chunkSize = 2 * 1024 * 1024;
  const chunkCount = Math.ceil(file.size / chunkSize);
  const init = new FormData();
  init.append("filename", file.name);
  init.append("content_hash", contentHash);
  init.append("file_size", file.size);
  init.append("chunk_size", chunkSize);
  init.append("chunk_count", chunkCount);
  init.append("parent_id", parentId || "");
  const session = await postForm("/files/upload/init/", init);
  for (let part = 1; part <= chunkCount; part++) {
    const chunk = file.slice((part - 1) * chunkSize, Math.min(part * chunkSize, file.size));
    const body = new FormData();
    body.append("part_number", part);
    body.append("chunk", chunk, file.name);
    await postForm(`/files/upload/${session.session_id}/chunk/`, body);
    setUploadProgress(item, Math.max(5, part * 95 / chunkCount), `分片上传 ${part}/${chunkCount}`, "");
  }
  await postForm(`/files/upload/${session.session_id}/merge/`, new FormData());
  setUploadProgress(item, 100, "上传完成", "done");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

async function streamForm(form, target, asChat) {
  const data = new FormData(form);
  const userText = String(data.get("message") || data.get("query") || "").trim();
  if (!userText) {
    const textarea = form.querySelector("textarea[name='message'], textarea[name='query']");
    if (textarea) textarea.focus();
    return;
  }
  const submit = form.querySelector("button[type='submit']");
  if (submit) submit.disabled = true;
  let output;
  if (asChat) {
    appendChatMessage(target, "user", userText);
    output = appendChatMessage(target, "assistant", "");
    const textarea = form.querySelector("textarea[name='message']");
    if (textarea) textarea.value = "";
  } else {
    target.innerHTML = "";
    target.classList.add("answer-box");
    output = target;
  }
  const processing = showProcessingIndicator(output);
  scrollToBottom(target);
  try {
    const response = await fetch(form.dataset.streamUrl, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      body: data,
    });
    if (!response.ok || !response.body) {
      throw new Error(`请求失败：${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data:")) continue;
        let payload;
        try {
          payload = JSON.parse(part.slice(5).trim());
        } catch (err) {
          throw new Error("响应解析失败");
        }
        if (payload.type === "token") {
          removeProcessingIndicator(processing);
          appendToken(output, payload.data);
        }
        if (payload.type === "conversation") {
          updateCurrentConversation(payload.data);
        }
        if (payload.type === "references") {
          removeProcessingIndicator(processing);
          renderReferences(output, payload.data?.references || []);
        }
        if (payload.type === "done") removeProcessingIndicator(processing);
        scrollToBottom(target);
      }
    }
    if (!asChat) {
      form.reset();
    }
  } catch (err) {
    removeProcessingIndicator(processing);
    appendError(output, err.message || "请求失败");
  } finally {
    removeProcessingIndicator(processing);
    if (submit) submit.disabled = false;
  }
  scrollToBottom(target);
}

function updateCurrentConversation(conversation) {
  if (!conversation?.id) return;
  const input = document.querySelector("#assistant-form input[name='conversation_id']");
  if (input) input.value = conversation.id;
  const active = document.querySelector(".assistant-conversation.active span");
  if (active && conversation.title) active.textContent = conversation.title;
  if (conversation.url) history.replaceState(null, "", conversation.url);
}

function appendChatMessage(target, role, text) {
  const message = document.createElement("div");
  message.className = `chat-message chat-message-${role}`;

  const avatar = document.createElement("div");
  avatar.className = "chat-avatar";
  avatar.textContent = role === "user" ? "我" : "AI";

  const body = document.createElement("div");
  body.className = "chat-message-body";

  const name = document.createElement("div");
  name.className = "chat-message-name";
  name.textContent = role === "user" ? "我" : "AI助手";

  const content = document.createElement("div");
  content.className = "chat-message-content";
  const markdown = document.createElement("div");
  markdown.className = "chat-markdown";
  markdown.dataset.markdownOutput = "1";
  content.appendChild(markdown);
  appendToken(content, text);

  body.append(name, content);
  message.append(avatar, body);
  target.appendChild(message);
  return content;
}

function appendToken(output, text) {
  if (!text) return;
  const target = output.querySelector("[data-markdown-output]") || output;
  target.dataset.rawText = `${target.dataset.rawText || ""}${String(text)}`;
  target.innerHTML = renderAssistantMarkdown(target.dataset.rawText);
}

function showProcessingIndicator(output) {
  const processing = document.createElement("div");
  processing.className = "assistant-processing";
  processing.innerHTML = '<span class="assistant-spinner" aria-hidden="true"></span><span>正在处理</span>';
  output.appendChild(processing);
  return processing;
}

function removeProcessingIndicator(processing) {
  if (processing && processing.parentNode) processing.remove();
}

function appendError(output, message) {
  const error = document.createElement("div");
  error.className = "stream-error";
  error.textContent = message;
  output.appendChild(error);
}

function renderReferences(output, references) {
  if (!references.length) return;
  const details = document.createElement("details");
  details.className = "assistant-references";

  const summary = document.createElement("summary");
  summary.textContent = `引用来源 ${references.length}`;

  const list = document.createElement("div");
  list.className = "reference-list";
  references.forEach((reference) => list.appendChild(referenceCard(reference)));

  details.append(summary, list);
  output.appendChild(details);
}

function referenceCard(reference) {
  const card = document.createElement("div");
  card.className = "reference-card";

  const title = document.createElement("div");
  title.className = "reference-title";

  const titleText = document.createElement(reference.url ? "a" : "span");
  titleText.textContent = reference.title || reference.source || "未命名来源";
  if (reference.url) titleText.href = reference.url;

  const type = document.createElement("span");
  type.className = "reference-type";
  type.textContent = reference.type === "wiki_page" ? "Wiki" : "原文";

  title.append(titleText, type);

  const meta = document.createElement("div");
  meta.className = "reference-meta";
  const ids = [];
  if (reference.page_type) ids.push(reference.page_type);
  if (reference.wiki_page_id) ids.push(`wiki#${reference.wiki_page_id}`);
  if (reference.chunk_id) ids.push(`chunk#${reference.chunk_id}`);
  if (reference.score !== undefined && reference.score !== null) ids.push(`score ${reference.score}`);
  meta.textContent = [reference.source, ...ids].filter(Boolean).join(" · ");

  card.append(title, meta);
  return card;
}

function scrollToBottom(target) {
  target.scrollTop = target.scrollHeight;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  }[ch]));
}

function renderAssistantMarkdown(value) {
  const text = String(value || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = text.split("\n");
  const html = [];
  let listType = "";

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = "";
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      return;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const ordered = line.match(/^(\d+)[.)]\s+(.+)$/);
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 6);
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    if (ordered) {
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${renderInlineMarkdown(ordered[2])}</li>`);
      return;
    }
    if (unordered) {
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${renderInlineMarkdown(unordered[1])}</li>`);
      return;
    }

    closeList();
    html.push(`<p>${renderInlineMarkdown(line)}</p>`);
  });

  closeList();
  return html.join("");
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}
