const apiBase = "/api";

const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("pdf-file");
const uploadStatus = document.getElementById("upload-status");
const documentList = document.getElementById("document-list");
const refreshDocsBtn = document.getElementById("refresh-docs");
const docFilter = document.getElementById("doc-filter");
const chatForm = document.getElementById("chat-form");
const questionInput = document.getElementById("question-input");
const answerOutput = document.getElementById("answer-output");
const referencesOutput = document.getElementById("references-output");
const intentTag = document.getElementById("intent-tag");
const normalizedQuestion = document.getElementById("question-normalized");
const clearBtn = document.getElementById("clear-btn");
const voiceBtn = document.getElementById("voice-btn");
const documentTemplate = document.getElementById("document-item-template");
const chatSubmitBtn = chatForm.querySelector('button[type="submit"]');

let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let isRecording = false;

async function request(url, options = {}) {
  const response = await fetch(`${apiBase}${url}`, options);
  const data = await response.json();
  if (!response.ok || data.success === false) {
    throw new Error(data.message || "Request failed");
  }
  return data;
}

function setUploadStatus(text) {
  uploadStatus.textContent = text;
}

function renderDocuments(items) {
  documentList.innerHTML = "";
  docFilter.innerHTML = "";

  if (!items.length) {
    documentList.innerHTML = `<div class="document-item"><p class="doc-meta">暂无文档</p></div>`;
    return;
  }

  items.forEach((item) => {
    const node = documentTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".doc-name").textContent = item.file_name;
    node.querySelector(".doc-meta").textContent = `状态: ${item.status} | 页数: ${item.page_count} | 切片: ${item.chunk_count}`;
    node.querySelector(".delete-doc-btn").addEventListener("click", async () => {
      try {
        await request(`/documents/${item.doc_id}`, { method: "DELETE" });
        await loadDocuments();
      } catch (error) {
        alert(error.message);
      }
    });
    documentList.appendChild(node);

    const option = document.createElement("option");
    option.value = item.doc_id;
    option.textContent = `${item.file_name} (${item.status})`;
    docFilter.appendChild(option);
  });
}

async function loadDocuments() {
  const result = await request("/documents");
  renderDocuments(result.data);
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!fileInput.files.length) {
    alert("请选择 PDF 文件");
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  try {
    setUploadStatus("解析中");
    await request("/documents/upload", {
      method: "POST",
      body: formData,
    });
    setUploadStatus("上传完成");
    fileInput.value = "";
    await loadDocuments();
  } catch (error) {
    setUploadStatus("失败");
    alert(error.message);
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const selectedDocIds = Array.from(docFilter.selectedOptions).map((option) => option.value);
  const question = questionInput.value.trim();
  if (!question) {
    return;
  }

  answerOutput.textContent = "正在生成答案...";
  referencesOutput.innerHTML = "";
  intentTag.textContent = "分析中";
  normalizedQuestion.textContent = question;
  questionInput.value = "";
  questionInput.blur();
  chatSubmitBtn.disabled = true;
  chatSubmitBtn.textContent = "生成中...";

  try {
    const result = await request("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        doc_ids: selectedDocIds.length ? selectedDocIds : null,
      }),
    });

    answerOutput.textContent = result.data.answer;
    intentTag.textContent = result.data.intent;
    normalizedQuestion.textContent = result.data.normalized_question;

    if (!result.data.references.length) {
      referencesOutput.innerHTML = `<div class="reference-item"><p class="reference-meta">未检索到证据</p></div>`;
      return;
    }

    result.data.references.forEach((item) => {
      const wrapper = document.createElement("div");
      wrapper.className = "reference-item";
      wrapper.innerHTML = `
        <p class="reference-meta">${item.source_file} | 页码 ${item.page} | 分数 ${item.score.toFixed(4)}</p>
        <div>${escapeHtml(item.text)}</div>
      `;
      referencesOutput.appendChild(wrapper);
    });
  } catch (error) {
    answerOutput.textContent = "问答失败";
    questionInput.value = question;
    alert(error.message);
  } finally {
    chatSubmitBtn.disabled = false;
    chatSubmitBtn.textContent = "开始问答";
    questionInput.focus();
  }
});

clearBtn.addEventListener("click", () => {
  questionInput.value = "";
  answerOutput.textContent = "等待提问...";
  referencesOutput.innerHTML = "";
  intentTag.textContent = "未分析";
  normalizedQuestion.textContent = "-";
  questionInput.focus();
});

refreshDocsBtn.addEventListener("click", loadDocuments);

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

voiceBtn.addEventListener("click", async () => {
  if (isRecording) {
    stopRecording();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    alert("当前浏览器不支持录音");
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

      try {
        const mimeType = mediaRecorder && mediaRecorder.mimeType ? mediaRecorder.mimeType : "audio/webm";
        const audioBlob = new Blob(audioChunks, { type: mimeType });
        const extension = resolveExtension(mimeType);
        const formData = new FormData();
        formData.append("file", audioBlob, `voice-input.${extension}`);

        const result = await request("/speech/transcribe", {
          method: "POST",
          body: formData,
        });

        questionInput.value = result.data.text.trim();
        questionInput.focus();
      } catch (error) {
        alert(`语音转写失败: ${error.message}`);
      } finally {
        cleanupRecorder();
        voiceBtn.disabled = false;
        voiceBtn.textContent = "语音输入";
      }
    };

    mediaRecorder.start();
    isRecording = true;
    voiceBtn.textContent = "停止录音";
  } catch (error) {
    cleanupRecorder();
    alert("无法访问麦克风，请检查浏览器权限");
  }
});

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

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML.replace(/\n/g, "<br>");
}

loadDocuments().catch((error) => {
  documentList.innerHTML = `<div class="document-item"><p class="doc-meta">${error.message}</p></div>`;
});
