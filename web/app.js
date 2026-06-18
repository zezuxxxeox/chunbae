const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messages = document.querySelector("#messages");
const submitButton = form.querySelector(".composer-box button");
const composerBox = form.querySelector(".composer-box");
const chatShell = document.querySelector(".chat-shell");
const quickActions = document.querySelector(".quick-actions");
const quickButtons = [...document.querySelectorAll(".quick-actions button")];

const AVATAR_SRC = "/assets/park-chunbae-avatar.png?v=filled-20260618";
const HISTORY_LIMIT = 12;
const conversationHistory = [];
let viewportRaf = 0;
let composerRaf = 0;
let scrollHideTimer = 0;
let lastQuickSubmitAt = 0;
let quickOpenTimer = 0;
const EDITABLE_VALUE = "plaintext-only";

function isMobileLayout() {
  return window.matchMedia("(max-width: 720px)").matches;
}

function syncViewportHeight() {
  if (viewportRaf) cancelAnimationFrame(viewportRaf);
  viewportRaf = requestAnimationFrame(() => {
    const viewport = window.visualViewport;
    const isMobile = isMobileLayout();
    const viewportHeight = viewport ? viewport.height : window.innerHeight;
    const viewportOffsetTop = viewport && isMobile ? viewport.offsetTop : 0;
    const keyboardOpen = isMobile && viewportHeight < window.innerHeight - 80;
    const appHeight = isMobile && viewport ? viewportHeight : window.innerHeight;

    document.documentElement.style.setProperty("--app-height", `${Math.round(appHeight)}px`);
    document.documentElement.style.setProperty("--viewport-offset-top", `${Math.round(viewportOffsetTop)}px`);
    document.documentElement.style.setProperty("--keyboard-inset", "0px");
    document.documentElement.style.setProperty("--composer-bottom-padding", keyboardOpen ? "8px" : "16px");
  });
}

function syncComposerHeight() {
  if (composerRaf) cancelAnimationFrame(composerRaf);
  composerRaf = requestAnimationFrame(() => {
    const formRect = form.getBoundingClientRect();
    const boxRect = composerBox.getBoundingClientRect();
    const shellRect = chatShell.getBoundingClientRect();
    const height = Math.ceil(formRect.height || 92);
    const quickBottom = Math.max(82, Math.ceil(shellRect.bottom - boxRect.top + 24));

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

function getInputText() {
  return String(input.innerText || input.textContent || "").replace(/\u00a0/g, " ");
}

function setInputText(text) {
  input.textContent = text;
  autosize();
}

function setInputEditable(isEditable) {
  input.setAttribute("contenteditable", isEditable ? EDITABLE_VALUE : "false");
  input.setAttribute("aria-disabled", isEditable ? "false" : "true");
}

function placeCaretAtEnd() {
  const selection = window.getSelection?.();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(input);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function focusInputWithoutScroll() {
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  enableTyping();
  try {
    input.focus({ preventScroll: true });
  } catch {
    input.focus();
  }
  placeCaretAtEnd();
  window.scrollTo(scrollX, scrollY);
  requestAnimationFrame(() => {
    window.scrollTo(scrollX, scrollY);
    syncViewportHeight();
    syncComposerHeight();
  });
}

function openQuickActions() {
  clearTimeout(quickOpenTimer);
  form.classList.add("quick-open");
  quickActions?.classList.add("quick-open");
  quickActions?.setAttribute("aria-hidden", "false");
  updateSuggestions();
  syncComposerHeight();
}

function closeQuickActions() {
  clearTimeout(quickOpenTimer);
  form.classList.remove("quick-open");
  quickActions?.classList.remove("quick-open");
  quickActions?.setAttribute("aria-hidden", "true");
  syncComposerHeight();
}

function scheduleQuickActions() {
  clearTimeout(quickOpenTimer);
  quickOpenTimer = setTimeout(openQuickActions, 180);
}

function enableTyping() {
  form.classList.remove("typing-idle");
  setInputEditable(true);
}

function clearTypingFocus({ freezeInput = false } = {}) {
  if (freezeInput) {
    form.classList.add("typing-idle");
    setInputEditable(false);
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
  const query = normalizeText(getInputText());
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

async function submitMessage(rawMessage, { refocus = false } = {}) {
  const message = rawMessage.trim();
  if (!message) return;

  addMessage(message, "user");
  setInputText("");
  closeQuickActions(); // 전송하면 고정질문 패널을 접는다(답변받을 때 안 펼쳐지게)
  clearTypingFocus({ freezeInput: true });
  syncViewportHeight();
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
  event?.preventDefault?.();
  await submitMessage(getInputText());
}

// 고정질문은 입력창을 '직접 누를 때'만 펼친다.
// (직접 타이핑하거나, 전송 후 자동 재포커스될 때는 펼치지 않는다)
input.addEventListener("click", scheduleQuickActions);
composerBox.addEventListener("pointerdown", (event) => {
  if (event.target.closest("button")) return;
  if (!isMobileLayout()) return;
  event.preventDefault();
  focusInputWithoutScroll();
  scheduleQuickActions();
});
input.addEventListener("pointerdown", () => {
  if (!isMobileLayout()) enableTyping();
});
input.addEventListener("focus", () => {
  enableTyping();
  setTimeout(() => {
    syncViewportHeight();
    syncComposerHeight();
  }, 80);
  scheduleQuickActions();
});
input.addEventListener("input", () => {
  updateSuggestions();
  autosize();
});
input.addEventListener("paste", (event) => {
  event.preventDefault();
  const text = event.clipboardData?.getData("text/plain") || "";
  document.execCommand("insertText", false, text);
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage(event);
  }
  if (event.key === "Escape") closeQuickActions();
});
submitButton.addEventListener("click", sendMessage);
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
  if (!form.contains(event.target) && !quickActions.contains(event.target) && !getInputText().trim()) {
    closeQuickActions();
  }
});

// 안내 팝업: 매 접속(새로고침 포함)마다 보여준다 -> 모든 방문자가 반드시 본다.
// 확인을 누르면 닫히고 챗봇이 나타난다.
function preventZoom(event) {
  event.preventDefault();
}

document.addEventListener("gesturestart", preventZoom, { passive: false });
document.addEventListener("gesturechange", preventZoom, { passive: false });
document.addEventListener("gestureend", preventZoom, { passive: false });
document.addEventListener(
  "touchmove",
  (event) => {
    if (event.touches && event.touches.length > 1) preventZoom(event);
  },
  { passive: false }
);
document.addEventListener(
  "wheel",
  (event) => {
    if (event.ctrlKey) preventZoom(event);
  },
  { passive: false }
);

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

autosize();
