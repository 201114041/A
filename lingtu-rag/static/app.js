const conversation = document.querySelector("#conversation");
const queryForm = document.querySelector("#queryForm");
const questionInput = document.querySelector("#question");
const sendButton = document.querySelector("#sendButton");
const sourcePanel = document.querySelector("#sourcePanel");
const sourceList = document.querySelector("#sourceList");
const retrievalMeta = document.querySelector("#retrievalMeta");
const modeSelect = document.querySelector("#mode");
const modeHint = document.querySelector("#modeHint");

let busy = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showToast(message, error = false) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.className = `toast show${error ? " error" : ""}`;
  setTimeout(() => { toast.className = "toast"; }, 3000);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败：${response.status}`);
  return payload;
}

function addMessage(role, text, pending = false) {
  const article = element("article", `message ${role}${pending ? " pending" : ""}`);
  article.append(element("div", "message-label", role === "user" ? "YOU" : "ANIME RAG"));
  const body = element("div", "message-body", text);
  article.append(body);
  conversation.append(article);
  conversation.scrollTop = conversation.scrollHeight;
  return article;
}

function renderSources(result) {
  sourceList.replaceChildren();
  const sources = result.sources || [];
  sourcePanel.classList.toggle("hidden", !sources.length);
  const modeLabel = result.mode === "llm" ? "LLM 生成" : "抽取式 RAG";
  retrievalMeta.textContent = `${sources.length} 条来源 · ${result.retrieval_ms} ms · ${modeLabel}`;
  for (const [index, source] of sources.entries()) {
    const card = element("article", "source-card");
    const top = element("div", "source-top");
    const titleBlock = element("div");
    titleBlock.append(
      element("div", "source-title", `${index + 1}. ${source.title}`),
      element("div", "source-meta", `${source.section} · ${source.id}`),
    );
    top.append(titleBlock, element("span", "source-page", `p.${source.page_start}${source.page_end !== source.page_start ? `-${source.page_end}` : ""}`));
    card.append(top, element("p", "source-text", source.text));
    if (source.source_excerpt_ja) {
      card.append(element("p", "source-excerpt", `日文原文线索：${source.source_excerpt_ja}`));
    }
    const terms = element("div", "source-terms");
    for (const keyword of (source.keywords || []).slice(0, 8)) terms.append(element("span", "", keyword));
    card.append(terms, element("div", "source-score", `BM25 score ${source.score} · matched: ${(source.matched_terms || []).slice(0, 5).join(", ")}`));
    sourceList.append(card);
  }
}

async function ask(question) {
  if (busy || !question.trim()) return;
  busy = true;
  sendButton.disabled = true;
  addMessage("user", question.trim());
  const pending = addMessage("assistant", "正在检索知识条目并核对来源", true);
  try {
    const result = await request("/api/query", {
      method: "POST",
      body: JSON.stringify({
        question: question.trim(),
        mode: modeSelect.value,
        top_k: Number(document.querySelector("#topK").value),
      }),
    });
    pending.remove();
    const modeNote = result.insufficient ? "资料不足" : (result.mode === "llm" ? "LLM 生成" : "抽取式 RAG");
    addMessage("assistant", `【${modeNote}】\n\n${result.answer}`);
    renderSources(result);
  } catch (error) {
    pending.remove();
    addMessage("assistant", `查询失败：${error.message}`);
    showToast(error.message, true);
  } finally {
    busy = false;
    sendButton.disabled = false;
    questionInput.focus();
  }
}

queryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = questionInput.value;
  if (!question.trim()) return;
  ask(question);
  questionInput.value = "";
});

document.querySelectorAll("#examples button").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.textContent;
    ask(button.textContent);
    questionInput.value = "";
  });
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    queryForm.requestSubmit();
  }
});

async function initialize() {
  try {
    const [health, summary] = await Promise.all([
      request("/api/health"),
      request("/api/eval/summary").catch(() => null),
    ]);
    document.querySelector("#healthText").textContent = health.llm_configured
      ? "知识库在线 · LLM 已配置"
      : "知识库在线 · 抽取式模式";
    document.querySelector("#docCount").textContent = health.documents;
    document.querySelector("#pageCount").textContent = `${health.page_span[1]}页`;
    if (summary) {
      document.querySelector("#hitAt1").textContent = `${(summary.hit_at_1 * 100).toFixed(1)}%`;
      const meta = document.querySelector(".stat.accent small");
      meta.textContent = `Recall@1 · ${summary.answerable_questions}题`;
    }
    if (!health.llm_configured) {
      const llmOption = modeSelect.querySelector('option[value="llm"]');
      llmOption.disabled = true;
      llmOption.textContent = "LLM 生成（未配置）";
      modeHint.textContent = "当前未配置 LLM API，将使用 BM25 检索 + 原文抽取回答；检索与引用仍完整可验证。";
    }
  } catch (error) {
    document.querySelector("#healthText").textContent = "知识库连接异常";
    showToast(error.message, true);
  }
}

initialize();
