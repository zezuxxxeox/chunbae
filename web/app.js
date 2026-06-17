const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messages = document.querySelector("#messages");
const submitButton = form.querySelector(".composer-box button");
const quickActions = document.querySelector(".quick-actions");
const quickButtons = [...document.querySelectorAll(".quick-actions button")];

const AVATAR_SRC = "/assets/park-chunbae-avatar.png";
const HISTORY_LIMIT = 12;
const conversationHistory = [];

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

function autosize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

function openQuickActions() {
  form.classList.add("quick-open");
  quickActions?.setAttribute("aria-hidden", "false");
  updateSuggestions();
}

function closeQuickActions() {
  form.classList.remove("quick-open");
  quickActions?.setAttribute("aria-hidden", "true");
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
    if (refocus) input.focus(); // 고정질문 전송 때는 재포커스하지 않아 닫힌 채로 둔다
  }
}

async function sendMessage(event) {
  event.preventDefault();
  await submitMessage(input.value);
}

input.addEventListener("focus", openQuickActions);
input.addEventListener("click", openQuickActions); // 채팅창을 직접 누르면 다시 연다
input.addEventListener("input", () => {
  openQuickActions();
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
quickButtons.forEach((button) => {
  button.addEventListener("click", () => {
    closeQuickActions();
    input.blur(); // 고정질문을 누르면 채팅창 포커스를 해제한다(다시 누르기 전까지 닫힌 채로)
    submitMessage(button.dataset.message || button.textContent || "", { refocus: false });
  });
});
document.addEventListener("click", (event) => {
  if (!form.contains(event.target) && !input.value.trim()) closeQuickActions();
});

// 첫 접속 안내 팝업: 확인을 누르면 닫히고 챗봇이 나타난다(브라우저당 한 번만).
const introNotice = document.querySelector("#introNotice");
const noticeClose = document.querySelector("#noticeClose");
if (introNotice) {
  let seen = false;
  try {
    seen = localStorage.getItem("chunbae_notice_seen") === "1";
  } catch (_) {
    seen = false;
  }
  if (!seen) introNotice.hidden = false;
}
noticeClose?.addEventListener("click", () => {
  if (introNotice) introNotice.hidden = true;
  try {
    localStorage.setItem("chunbae_notice_seen", "1");
  } catch (_) {
    /* localStorage 막혀 있어도 무시 */
  }
});

autosize();
