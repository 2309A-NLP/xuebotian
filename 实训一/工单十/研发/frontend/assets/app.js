const apiBase = "/api";
const sessionsStorageKey = "raggd_chat_sessions_v1";

const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("pdf-file");
const uploadStatus = document.getElementById("upload-status");
const documentList = document.getElementById("document-list");
const refreshDocsBtn = document.getElementById("refresh-docs");
const chatForm = document.getElementById("chat-form");
const questionInput = document.getElementById("question-input");
const chatMessages = document.getElementById("chat-messages");
const clearBtn = document.getElementById("clear-btn");
const voiceBtn = document.getElementById("voice-btn");
const logoutBtn = document.getElementById("logout-btn");
const currentUserName = document.getElementById("current-user-name");
const documentTemplate = document.getElementById("document-item-template");
const chatSubmitBtn = chatForm.querySelector('button[type="submit"]');
const pageStatus = document.getElementById("page-status");
const newSessionBtn = document.getElementById("new-session-btn");
const sessionList = document.getElementById("session-list");

let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let isRecording = false;
let streamInProgress = false;

let pendingAnswerDelta = "";
let renderedAnswer = "";
let answerFlushScheduled = false;
let activeAssistantMessage = null;

let sessions = [];
let activeSessionId = "";

function showPageStatus(message, tone = "info") {
  pageStatus.textContent = message;
  pageStatus.className = `inline-notice inline-notice--${tone}`;
}

function redirectToLogin(reason = "expired") {
  const query = new URLSearchParams({ message: reason });
  window.location.href = `/login?${query.toString()}`;
}

async function request(url, options = {}, { handleUnauthorized = true } = {}) {
  const response = await fetch(`${apiBase}${url}`, {
    credentials: "same-origin",
    ...options,
  });

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (response.status === 401 && handleUnauthorized) {
    redirectToLogin("expired");
    throw new Error("当前登录状态已失效，请重新登录。");
  }

  if (!response.ok || !data || data.success === false) {
    throw new Error(data?.message || "请求失败，请稍后重试。");
  }

  return data;
}

async function ensureAuthenticated() {
  try {
    const result = await request("/auth/me", {}, { handleUnauthorized: false });
    currentUserName.textContent = `已登录账号：${result.data.username}`;
    return result.data;
  } catch (error) {
    redirectToLogin("login_required");
    throw error;
  }
}

function setUploadStatus(text, state = "idle") {
  uploadStatus.textContent = text;
  uploadStatus.dataset.state = state;
}

function formatDocumentStatus(status) {
  const mapping = {
    ready: "已就绪",
    indexing: "处理中",
    parsing: "处理中",
    uploaded: "已上传",
    failed: "处理失败",
  };
  return mapping[status] || "处理中";
}

function renderDocuments(items) {
  documentList.innerHTML = "";

  if (!items.length) {
    documentList.innerHTML =
      '<div class="document-item"><p class="doc-meta">当前还没有文档。</p></div>';
    return;
  }

  items.forEach((item) => {
    const node = documentTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".doc-name").textContent = item.file_name;
    node.querySelector(".doc-meta").textContent = formatDocumentStatus(item.status);
    node.querySelector(".delete-doc-btn").addEventListener("click", async () => {
      const confirmed = window.confirm(`确认删除文档“${item.file_name}”吗？删除后无法恢复。`);
      if (!confirmed) {
        return;
      }

      try {
        showPageStatus("正在删除文档，请稍候。", "info");
        await request(`/documents/${item.doc_id}`, { method: "DELETE" });
        await loadDocuments();
        showPageStatus("文档已删除，列表已刷新。", "success");
      } catch (error) {
        showPageStatus(error.message, "error");
        alert(error.message);
      }
    });
    documentList.appendChild(node);
  });
}

async function loadDocuments() {
  showPageStatus("正在加载文档列表。", "info");
  const result = await request("/documents");
  renderDocuments(result.data);
  showPageStatus("文档列表已更新。你可以上传新文档或直接开始提问。", "success");
}

function scrollMessagesToBottom() {
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function formatTime(date = new Date()) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function nowIso() {
  return new Date().toISOString();
}

function createSession(title = "新会话") {
  return {
    id: `session_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
    title,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    messages: [],
  };
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(sessionsStorageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      sessions = parsed.filter((item) => item && Array.isArray(item.messages));
    }
  } catch {
    sessions = [];
  }

  if (!sessions.length) {
    const session = createSession();
    sessions = [session];
  }

  if (!activeSessionId || !sessions.some((item) => item.id === activeSessionId)) {
    activeSessionId = sessions[0].id;
  }
}

function saveSessions() {
  localStorage.setItem(sessionsStorageKey, JSON.stringify(sessions));
}

function getActiveSession() {
  return sessions.find((item) => item.id === activeSessionId) || null;
}

function touchActiveSession() {
  const session = getActiveSession();
  if (!session) {
    return;
  }
  session.updatedAt = nowIso();
}

function sessionTitleFromMessages(messages) {
  const firstUser = messages.find((item) => item.role === "user" && item.text.trim());
  if (!firstUser) {
    return "新会话";
  }
  return firstUser.text.trim().slice(0, 24);
}

function syncActiveSessionTitle() {
  const session = getActiveSession();
  if (!session) {
    return;
  }
  session.title = sessionTitleFromMessages(session.messages);
}

function sortSessionsByUpdatedAt(items) {
  return [...items].sort((left, right) => {
    return String(right.updatedAt).localeCompare(String(left.updatedAt));
  });
}

async function clearRemoteSessionHistory(sessionId) {
  if (!sessionId) {
    return;
  }
  await request(`/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}

async function removeSession(sessionId) {
  const target = sessions.find((item) => item.id === sessionId);
  if (!target) {
    return;
  }
  const wasActive = activeSessionId === sessionId;
  await clearRemoteSessionHistory(sessionId);

  sessions = sessions.filter((item) => item.id !== sessionId);

  if (!sessions.length) {
    const session = createSession();
    sessions = [session];
    activeSessionId = session.id;
  } else if (activeSessionId === sessionId || !sessions.some((item) => item.id === activeSessionId)) {
    activeSessionId = sortSessionsByUpdatedAt(sessions)[0].id;
  }

  saveSessions();
  if (wasActive) {
    renderActiveSession();
  } else {
    renderSessionList();
  }
  showPageStatus(`会话“${target.title || "新会话"}”已删除。`, "success");
}

function renderSessionList() {
  sessionList.innerHTML = "";

  const sorted = sortSessionsByUpdatedAt(sessions);

  sorted.forEach((session) => {
    const row = document.createElement("div");
    row.className = "session-row";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-item";
    if (session.id === activeSessionId) {
      button.classList.add("session-item--active");
    }

    const title = document.createElement("strong");
    title.textContent = session.title || "新会话";

    const meta = document.createElement("span");
    meta.textContent = `${session.messages.length} 条消息`;

    button.append(title, meta);
    button.addEventListener("click", () => {
      if (streamInProgress || session.id === activeSessionId) {
        return;
      }
      activeSessionId = session.id;
      renderActiveSession();
      saveSessions();
      showPageStatus(`已切换到会话：${session.title || "新会话"}`, "success");
    });

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "ghost-btn session-delete-btn";
    deleteBtn.textContent = "删除";
    deleteBtn.disabled = streamInProgress;
    deleteBtn.addEventListener("click", async () => {
      if (streamInProgress) {
        return;
      }
      const confirmed = window.confirm(`确认删除会话“${session.title || "新会话"}”吗？`);
      if (!confirmed) {
        return;
      }
      try {
        await removeSession(session.id);
      } catch (error) {
        showPageStatus(error.message, "error");
        alert(error.message);
      }
    });

    row.append(button, deleteBtn);
    sessionList.appendChild(row);
  });
}

function createMessage(role, text, options = {}) {
  const article = document.createElement("article");
  article.className = `chat-message chat-message--${role}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "assistant" ? "AI" : "你";

  const card = document.createElement("div");
  card.className = "message-card";

  const head = document.createElement("div");
  head.className = "message-head";

  const author = document.createElement("span");
  author.className = "message-author";
  author.textContent = role === "assistant" ? "文档助手" : "你";

  const time = document.createElement("span");
  time.className = "message-time";
  time.textContent = options.time || formatTime();

  head.append(author, time);

  const note = document.createElement("div");
  note.className = "message-note";

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;

  card.append(head);
  if (options.noteText || role === "assistant") {
    card.append(note);
  }
  card.append(body);

  article.append(avatar, card);
  chatMessages.appendChild(article);

  if (options.noteText) {
    const context = document.createElement("p");
    context.className = "message-context";
    context.textContent = options.noteText;
    note.appendChild(context);
  }

  return { article, note, body };
}

function renderStoredMessage(message) {
  const { article, note, body } = createMessage(message.role, message.text, {
    time: message.time,
  });

  if (message.role !== "assistant") {
    return { article, body };
  }

  const details = document.createElement("details");
  details.className = "message-sources";
  details.hidden = true;

  const summary = document.createElement("summary");
  summary.textContent = "引用 0 条";

  const list = document.createElement("div");
  list.className = "references-list";
  details.append(summary, list);
  article.querySelector(".message-card").appendChild(details);

  const view = { article, body, details, summary, list };
  if (Array.isArray(message.references) && message.references.length) {
    renderReferenceItems(message.references, view);
  }
  return view;
}

function renderReferenceItems(items, targetMessage = activeAssistantMessage) {
  if (!targetMessage) {
    return;
  }

  const { details, summary, list } = targetMessage;
  list.innerHTML = "";

  if (!items.length) {
    details.hidden = true;
    details.open = false;
    return;
  }

  summary.textContent = `查看依据（${items.length}）`;
  details.hidden = false;

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "reference-item";

    const head = document.createElement("div");
    head.className = "reference-head";

    const title = document.createElement("strong");
    title.textContent = item.source_file || "未命名文档";

    const meta = document.createElement("p");
    meta.className = "reference-meta";

    const pageText =
      item.page_end && item.page_end !== item.page ? `${item.page}-${item.page_end}` : `${item.page}`;
    meta.textContent = `页码 ${pageText}`;

    const text = document.createElement("div");
    text.className = "reference-text";
    text.textContent = item.text || "";

    head.append(title, meta);
    card.append(head, text);
    list.appendChild(card);
  });
}

function appendUserMessage(question) {
  return createMessage("user", question);
}

function appendAssistantMessage() {
  const { article, note, body } = createMessage("assistant", "正在整理回答，请稍候。");

  const details = document.createElement("details");
  details.className = "message-sources";
  details.hidden = true;

  const summary = document.createElement("summary");
  summary.textContent = "引用 0 条";

  const list = document.createElement("div");
  list.className = "references-list";

  details.append(summary, list);
  article.querySelector(".message-card").appendChild(details);

  scrollMessagesToBottom();
  return { article, body, details, summary, list };
}

function renderActiveSession() {
  resetAnswerStream();
  chatMessages.innerHTML = "";

  const session = getActiveSession();
  if (!session) {
    return;
  }

  session.messages.forEach((message) => {
    renderStoredMessage(message);
  });
  renderSessionList();
  scrollMessagesToBottom();
}

function pushAnswerDelta(delta) {
  pendingAnswerDelta += delta;
  if (!answerFlushScheduled) {
    answerFlushScheduled = true;
    requestAnimationFrame(() => flushAnswerBuffer(false));
  }
}

function flushAnswerBuffer(force) {
  if (!pendingAnswerDelta && !force) {
    answerFlushScheduled = false;
    return;
  }

  renderedAnswer += pendingAnswerDelta;
  pendingAnswerDelta = "";

  if (activeAssistantMessage) {
    activeAssistantMessage.body.textContent = renderedAnswer || "正在整理回答，请稍候。";
  }

  const session = getActiveSession();
  if (session && session.messages.length) {
    const last = session.messages[session.messages.length - 1];
    if (last.role === "assistant") {
      last.text = renderedAnswer;
    }
  }

  answerFlushScheduled = false;
  scrollMessagesToBottom();
}

function resetAnswerStream() {
  pendingAnswerDelta = "";
  renderedAnswer = "";
  answerFlushScheduled = false;
  activeAssistantMessage = null;
}

function setComposerDisabled(disabled) {
  streamInProgress = disabled;
  chatSubmitBtn.disabled = disabled;
  questionInput.disabled = disabled;
  clearBtn.disabled = disabled;
  newSessionBtn.disabled = disabled;
}

function autoResizeQuestionInput() {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 220)}px`;
}

function createNewSession() {
  if (streamInProgress) {
    return;
  }
  const session = createSession();
  sessions.unshift(session);
  activeSessionId = session.id;
  saveSessions();
  renderActiveSession();
  showPageStatus("已新建会话。", "success");
  questionInput.focus();
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) {
    showPageStatus("请先选择一个 PDF 文件再上传。", "error");
    alert("请先选择一个 PDF 文件再上传。");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  try {
    setUploadStatus("上传中", "loading");
    showPageStatus("文件已提交，正在处理中。", "info");
    await request("/documents/upload", {
      method: "POST",
      body: formData,
    });
    setUploadStatus("已提交", "ok");
    fileInput.value = "";
    await loadDocuments();
    showPageStatus("上传成功。", "success");
  } catch (error) {
    setUploadStatus("上传失败", "error");
    showPageStatus(error.message, "error");
    alert(error.message);
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const question = questionInput.value.trim();
  if (!question) {
    showPageStatus("请输入问题后再发送。", "error");
    return;
  }

  const session = getActiveSession();
  if (!session) {
    return;
  }

  const userMessage = {
    role: "user",
    text: question,
    time: formatTime(),
  };
  const assistantMessage = {
    role: "assistant",
    text: "",
    time: formatTime(),
    references: [],
  };
  session.messages.push(userMessage, assistantMessage);
  touchActiveSession();
  syncActiveSessionTitle();
  saveSessions();
  renderSessionList();

  appendUserMessage(question);
  resetAnswerStream();
  activeAssistantMessage = appendAssistantMessage();

  questionInput.value = "";
  autoResizeQuestionInput();
  questionInput.blur();
  setComposerDisabled(true);
  chatSubmitBtn.textContent = "生成中...";
  showPageStatus("问题已发送，正在生成回答。", "info");

  try {
    await streamChat(question, session.id);
    flushAnswerBuffer(true);
    touchActiveSession();
    syncActiveSessionTitle();
    saveSessions();
    renderSessionList();
    showPageStatus("回答已生成完成，你可以继续追问。", "success");
  } catch (error) {
    if (activeAssistantMessage) {
      activeAssistantMessage.body.textContent = "这次回答生成失败了，请稍后重试。";
    }
    const latestSession = getActiveSession();
    if (latestSession && latestSession.messages.length) {
      const last = latestSession.messages[latestSession.messages.length - 1];
      if (last.role === "assistant") {
        last.text = "这次回答生成失败了，请稍后重试。";
      }
    }
    saveSessions();
    questionInput.value = question;
    autoResizeQuestionInput();
    showPageStatus(error.message, "error");
    alert(error.message);
  } finally {
    setComposerDisabled(false);
    chatSubmitBtn.textContent = "发送问题";
    questionInput.focus();
  }
});

clearBtn.addEventListener("click", async () => {
  if (streamInProgress) {
    return;
  }
  const session = getActiveSession();
  if (!session) {
    return;
  }
  try {
    await clearRemoteSessionHistory(session.id);
    session.messages = [];
    session.title = "新会话";
    touchActiveSession();
    saveSessions();
    renderActiveSession();
    showPageStatus("当前会话已清空。", "success");
    questionInput.focus();
  } catch (error) {
    showPageStatus(error.message, "error");
    alert(error.message);
  }
});

newSessionBtn.addEventListener("click", createNewSession);

refreshDocsBtn.addEventListener("click", () => {
  loadDocuments().catch((error) => {
    showPageStatus(error.message, "error");
    alert(error.message);
  });
});

logoutBtn.addEventListener("click", async () => {
  try {
    logoutBtn.disabled = true;
    await request("/auth/logout", { method: "POST" }, { handleUnauthorized: false });
  } finally {
    window.location.href = "/login?message=logout";
  }
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

questionInput.addEventListener("input", autoResizeQuestionInput);

voiceBtn.addEventListener("click", async () => {
  if (isRecording) {
    stopRecording();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    const message = "当前浏览器不支持录音功能，请改用文字输入。";
    showPageStatus(message, "error");
    alert(message);
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    mediaRecorder = new MediaRecorder(mediaStream);

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    mediaRecorder.onstop = async () => {
      voiceBtn.disabled = true;
      voiceBtn.textContent = "转写中...";
      showPageStatus("录音已结束，正在转写语音内容。", "info");

      try {
        const mimeType = mediaRecorder?.mimeType || "audio/webm";
        const audioBlob = new Blob(audioChunks, { type: mimeType });
        const extension = resolveExtension(mimeType);
        const formData = new FormData();
        formData.append("file", audioBlob, `voice-input.${extension}`);

        const result = await request("/speech/transcribe", {
          method: "POST",
          body: formData,
        });

        questionInput.value = result.data.text.trim();
        autoResizeQuestionInput();
        questionInput.focus();
        showPageStatus("语音转写完成，内容已填入输入框。请确认后再发送。", "success");
      } catch (error) {
        showPageStatus(`语音转写失败：${error.message}`, "error");
        alert(`语音转写失败：${error.message}`);
      } finally {
        cleanupRecorder();
        voiceBtn.disabled = false;
        voiceBtn.textContent = "语音输入";
      }
    };

    mediaRecorder.start();
    isRecording = true;
    voiceBtn.textContent = "停止录音";
    showPageStatus("正在录音。再次点击按钮即可结束并开始转写。", "info");
  } catch {
    cleanupRecorder();
    const message = "无法访问麦克风，请检查浏览器权限后重试。";
    showPageStatus(message, "error");
    alert(message);
  }
});

async function streamChat(question, sessionId) {
  const response = await fetch(`${apiBase}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({
      question,
      session_id: sessionId,
      doc_ids: null,
    }),
  });

  if (response.status === 401) {
    redirectToLogin("expired");
    throw new Error("当前登录状态已失效，请重新登录。");
  }

  if (!response.ok || !response.body) {
    throw new Error("流式问答请求失败，请稍后重试。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";

    for (const eventBlock of events) {
      handleSseEvent(eventBlock);
    }
  }

  if (buffer.trim()) {
    handleSseEvent(buffer);
  }
}

function handleSseEvent(eventBlock) {
  const lines = eventBlock.split("\n");
  let eventName = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }

  if (!data) {
    return;
  }

  const payload = JSON.parse(data);
  const session = getActiveSession();

  if (eventName === "meta") {
    if (!activeAssistantMessage) {
      return;
    }
    renderReferenceItems(payload.references || []);
    activeAssistantMessage.body.textContent = "";

    if (session && session.messages.length) {
      const last = session.messages[session.messages.length - 1];
      if (last.role === "assistant") {
        last.references = payload.references || [];
      }
    }
    return;
  }

  if (eventName === "token") {
    pushAnswerDelta(payload.delta || "");
    return;
  }

  if (eventName === "done") {
    if (!renderedAnswer.trim() && !pendingAnswerDelta.trim() && activeAssistantMessage) {
      renderedAnswer = payload.answer || "";
      activeAssistantMessage.body.textContent = renderedAnswer || "未生成回答。";
    }
    if (session && session.messages.length) {
      const last = session.messages[session.messages.length - 1];
      if (last.role === "assistant") {
        last.text = renderedAnswer || payload.answer || "";
      }
    }
    return;
  }

  if (eventName === "error") {
    throw new Error(payload.message || "流式问答失败，请稍后重试。");
  }
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") {
    cleanupRecorder();
    return;
  }

  isRecording = false;
  voiceBtn.textContent = "处理中...";
  mediaRecorder.stop();
}

function cleanupRecorder() {
  isRecording = false;
  if (mediaRecorder) {
    mediaRecorder.ondataavailable = null;
    mediaRecorder.onstop = null;
  }
  mediaRecorder = null;
  audioChunks = [];

  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
  }
  mediaStream = null;
}

function resolveExtension(mimeType) {
  if (mimeType.includes("ogg")) {
    return "ogg";
  }
  if (mimeType.includes("mp4")) {
    return "mp4";
  }
  if (mimeType.includes("mpeg")) {
    return "mp3";
  }
  if (mimeType.includes("wav")) {
    return "wav";
  }
  return "webm";
}

async function boot() {
  autoResizeQuestionInput();
  await ensureAuthenticated();
  loadSessions();
  renderActiveSession();
  setUploadStatus("等待上传", "idle");
  await loadDocuments();
  showPageStatus("登录状态已确认，现在可以上传文档或开始提问。", "success");
}

boot().catch((error) => {
  showPageStatus(error.message || "页面初始化失败，请重新登录后重试。", "error");
});
