const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messages = document.querySelector("#messages");
const submitButton = form.querySelector(".composer-box button");
const composerBox = form.querySelector(".composer-box");
const quickActions = document.querySelector(".quick-actions");
const quickButtons = [...document.querySelectorAll(".quick-actions button")];

const AVATAR_SRC = "/assets/park-chunbae-avatar.png";
const HISTORY_LIMIT = 12;
const conversationHistory = [];
let viewportRaf = 0;
let composerRaf = 0;
let scrollHideTimer = 0;
let lastQuickSubmitAt = 0;

function syncViewportHeight() {
  if (viewportRaf) cancelAnimationFrame(viewportRaf);
  viewportRaf = requestAnimationFrame(() => {
    const viewport = window.visualViewport;
    const height = viewport ? viewport.height : window.innerHeight;
    const offsetTop = viewport ? viewport.offsetTop : 0;
    const keyboardInset = viewport ? Math.max(0, window.innerHeight - height - offsetTop) : 0;

    document.documentElement.style.setProperty("--app-height", `${Math.round(height)}px`);
    document.documentElement.style.setProperty("--keyboard-inset", `${Math.round(keyboardInset)}px`);
  });
}

function syncComposerHeight() {
  if (composerRaf) cancelAnimationFrame(composerRaf);
  composerRaf = requestAnimationFrame(() => {
    const formRect = form.getBoundingClientRect();
    const boxRect = composerBox.getBoundingClientRect();
    const height = Math.ceil(formRect.height || 92);
    const quickBottom = Math.max(68, Math.ceil(formRect.bottom - boxRect.top + 10));

    document.documentElement.style.setProperty("--composer-height", `${height}px`);
    document.documentElement.style.setProperty("--quick-actions-bottom", `${quickBottom}px`);
  });
}

function addMessage(text, role, flags = []) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  if (flags.length) article.classList.add("warning");

  if (role === "bot") {
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.src = AVATAR_SRC;
    avatar.alt = "";
    article.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const p = document.createElement("p");
  p.textContent = text;
  bubble.appendChild(p);
  article.appendChild(bubble);
  messages.appendChild(article);
  scrollToBottom();
  return article;
}

function textNode(messageEl) {
  return messageEl.querySelector(".bubble p");
}

function setText(messageEl, text) {
  textNode(messageEl).textContent = text;
  scrollToBottom();
}

function appendText(messageEl, text) {
  textNode(messageEl).textContent += text;
  scrollToBottom();
}

function friendlyErrorMessage(error) {
  const message = String(error?.message || "");
  if (message.includes("429") || message.toLowerCase().includes("quota")) {
    return "지금 공짜 LLM이 좀 막혔다 ㅡㅡ. 조금 천천히, 잠시 뒤 다시 물어봐라. 급하면 입력창 눌러서 뜨는 질문을 골라 눌러봐라. 그건 막힘없이 바로 답한다.";
  }
  if (message.includes("LLM이 꺼져") || message.includes("LLM 설정")) {
    return "LLM 설정이 아직 안 잡혔다. llm.env를 확인해라.";
  }
  return "처리 중에 잠깐 문제가 생겼다. 입력창 눌러서 뜨는 질문을 눌러보면 그건 바로 답한다.";
}

function scrollToBottom() {
  messages.scrollTop = messages.scrollHeight;
}

function markMessagesScrolling() {
  messages.classList.add("is-scrolling");
  clearTimeout(scrollHideTimer);
  scrollHideTimer = setTimeout(() => {
    messages.classList.remove("is-scrolling");
  }, 800);
}

function autosize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  syncComposerHeight();
}

function openQuickActions() {
  form.classList.add("quick-open");
  quickActions?.setAttribute("aria-hidden", "false");
  updateSuggestions();
  syncComposerHeight();
}

function closeQuickActions() {
  form.classList.remove("quick-open");
  quickActions?.setAttribute("aria-hidden", "true");
  syncComposerHeight();
}

function enableTyping() {
  form.classList.remove("typing-idle");
  input.readOnly = false;
}

function clearTypingFocus({ freezeInput = false } = {}) {
  if (freezeInput) {
    form.classList.add("typing-idle");
    input.readOnly = true;
  }
  input.blur();
  const active = document.activeElement;
  if (active instanceof HTMLElement && active !== document.body) {
    active.blur();
  }
  window.getSelection?.().removeAllRanges();
}

function submitQuickAction(button) {
  const now = Date.now();
  if (now - lastQuickSubmitAt < 450) return;
  lastQuickSubmitAt = now;
  closeQuickActions();
  clearTypingFocus({ freezeInput: true });
  submitMessage(button.dataset.message || button.textContent || "", { refocus: false });
}

function normalizeText(text) {
  return String(text || "").toLowerCase().replace(/\s+/g, "");
}

function updateSuggestions() {
  const query = normalizeText(input.value);
  let shown = 0;
  quickButtons.forEach((button) => {
    const haystack = normalizeText(`${button.dataset.message || ""} ${button.dataset.keywords || ""}`);
    const matches = !query || haystack.includes(query) || [...query].some((char) => haystack.includes(char));
    const shouldShow = matches && shown < 6;
    button.hidden = !shouldShow;
    if (shouldShow) shown += 1;
  });

  if (shown === 0) {
    quickButtons.slice(0, 4).forEach((button) => {
      button.hidden = false;
    });
  }
}

async function readStream(response, botMessage) {
  if (!response.ok || !response.body) {
    throw new Error((await response.text()) || "요청에 실패했습니다.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let started = false;

  async function handleLine(line) {
    if (!line.trim()) return;
    const event = JSON.parse(line);

    if (event.type === "error") {
      throw new Error(event.error || "요청에 실패했습니다.");
    }

    if (!started && (event.type === "delta" || event.type === "replace")) {
      started = true;
      botMessage.classList.remove("pending");
      botMessage.classList.add("streaming");
      setText(botMessage, "");
    }

    if (event.type === "delta") appendText(botMessage, event.text || "");
    if (event.type === "replace") setText(botMessage, event.text || "");

    if (event.type === "done") {
      botMessage.classList.remove("pending", "streaming");
      const flags = [...(event.input_flags || []), ...(event.output_flags || [])];
      if (flags.length) botMessage.classList.add("warning");
    }
  }

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) await handleLine(line);
  }

  buffer += decoder.decode();
  if (buffer.trim()) await handleLine(buffer);
  return textNode(botMessage).textContent.trim();
}

function rememberTurn(userText, botText) {
  if (!userText || !botText) return;
  conversationHistory.push(
    { role: "user", content: userText },
    { role: "assistant", content: botText }
  );
  if (conversationHistory.length > HISTORY_LIMIT) {
    conversationHistory.splice(0, conversationHistory.length - HISTORY_LIMIT);
  }
}

function setBusy(isBusy) {
  submitButton.disabled = isBusy;
  quickButtons.forEach((button) => {
    button.disabled = isBusy;
  });
}

async function submitMessage(rawMessage, { refocus = true } = {}) {
  const message = rawMessage.trim();
  if (!message) return;

  addMessage(message, "user");
  input.value = "";
  autosize();
  closeQuickActions(); // 전송하면 고정질문 패널을 접는다(답변받을 때 안 펼쳐지게)
  setBusy(true);

  const botMessage = addMessage("어. 잠깐만.", "bot");
  botMessage.classList.add("pending", "streaming");

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: conversationHistory.slice(-HISTORY_LIMIT) })
    });
    const replyText = await readStream(response, botMessage);
    rememberTurn(message, replyText);
  } catch (error) {
    botMessage.remove();
    addMessage(friendlyErrorMessage(error), "bot", ["error"]);
  } finally {
    setBusy(false);
    if (refocus) {
      input.focus();
    } else {
      clearTypingFocus({ freezeInput: true });
      requestAnimationFrame(() => clearTypingFocus({ freezeInput: true }));
    }
  }
}

async function sendMessage(event) {
  event.preventDefault();
  await submitMessage(input.value);
}

// 고정질문은 입력창을 '직접 누를 때'만 펼친다.
// (직접 타이핑하거나, 전송 후 자동 재포커스될 때는 펼치지 않는다)
input.addEventListener("click", openQuickActions);
input.addEventListener("pointerdown", enableTyping);
input.addEventListener("focus", () => {
  enableTyping();
  setTimeout(() => {
    syncViewportHeight();
    syncComposerHeight();
    scrollToBottom();
  }, 80);
});
input.addEventListener("input", () => {
  updateSuggestions();
  autosize();
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
  if (event.key === "Escape") closeQuickActions();
});
form.addEventListener("submit", sendMessage);
messages.addEventListener("scroll", markMessagesScrolling, { passive: true });
quickButtons.forEach((button) => {
  button.tabIndex = -1;
  button.addEventListener("mousedown", (event) => event.preventDefault());
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    clearTypingFocus({ freezeInput: true });
  });
  button.addEventListener("pointerup", (event) => {
    event.preventDefault();
    submitQuickAction(button);
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    submitQuickAction(button);
  });
});
document.addEventListener("click", (event) => {
  if (!form.contains(event.target) && !input.value.trim()) closeQuickActions();
});

// 안내 팝업: 매 접속(새로고침 포함)마다 보여준다 -> 모든 방문자가 반드시 본다.
// 확인을 누르면 닫히고 챗봇이 나타난다.
const introNotice = document.querySelector("#introNotice");
const noticeClose = document.querySelector("#noticeClose");
if (introNotice) introNotice.hidden = false;
noticeClose?.addEventListener("click", () => {
  if (introNotice) introNotice.hidden = true;
});

syncViewportHeight();
syncComposerHeight();
if ("ResizeObserver" in window) {
  new ResizeObserver(syncComposerHeight).observe(form);
}
window.addEventListener("resize", syncViewportHeight);
window.visualViewport?.addEventListener("resize", syncViewportHeight);
window.visualViewport?.addEventListener("scroll", syncViewportHeight);

autosize();
