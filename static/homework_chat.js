function renderMathIn(el) {
  if (window.renderMathInElement) {
    window.renderMathInElement(el, { delimiters: window.MATH_DELIMITERS, throwOnError: false });
  }
}

function initHomeworkChat(opts) {
  const card = document.getElementById(opts.cardId);
  const messagesEl = document.getElementById(opts.messagesId);
  const theoryBtn = document.getElementById(opts.theoryBtnId);
  const taskBtn = document.getElementById(opts.taskBtnId);
  const taskInput = document.getElementById(opts.taskInputId);
  const actionsEl = document.getElementById(opts.actionsId);
  const coinsEl = document.getElementById(opts.coinsId);
  const limitMsgEl = document.getElementById(opts.limitMsgId);
  if (!card || !theoryBtn || !taskBtn) return;

  const chatUrl = card.dataset.chatUrl;
  let remaining = opts.hintLimit;

  function addBubble(role, text) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    renderMathIn(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return wrap;
  }

  // Render math in the server-rendered chat history once KaTeX has loaded
  // (its <script defer> tags may not have run yet at this point in parsing).
  if (window.renderMathInElement) {
    renderMathIn(messagesEl);
  } else {
    document.addEventListener("DOMContentLoaded", () => renderMathIn(messagesEl));
  }

  function setBusy(busy) {
    theoryBtn.disabled = busy;
    taskBtn.disabled = busy;
    taskInput.disabled = busy;
  }

  function updateCoins() {
    if (coinsEl) {
      coinsEl.textContent = opts.coinsTemplate
        .replace("{n}", remaining)
        .replace("{total}", opts.hintLimit);
    }
    if (remaining <= 0) {
      actionsEl.hidden = true;
      if (limitMsgEl) limitMsgEl.hidden = false;
    }
  }

  async function sendAction(payload, userText) {
    setBusy(true);
    addBubble("user", userText);
    const typing = addBubble("bot typing", "…");

    try {
      const res = await fetch(chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      typing.remove();

      if (!res.ok) {
        addBubble("bot error", data.error || "Something went wrong.");
        if (res.status === 403) {
          remaining = 0;
          updateCoins();
        }
        return;
      }
      addBubble("bot", data.reply);
      remaining = data.remaining;
      updateCoins();
    } catch (err) {
      typing.remove();
      addBubble("bot error", "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  theoryBtn.addEventListener("click", () => {
    sendAction({ action: "theory" }, theoryBtn.textContent.trim());
  });

  taskBtn.addEventListener("click", () => {
    const taskNumber = taskInput.value.trim();
    if (!taskNumber) {
      taskInput.focus();
      addBubble("bot error", opts.taskNumberRequired);
      return;
    }
    sendAction({ action: "task_help", task_number: taskNumber }, `${taskBtn.textContent.trim()}: ${taskNumber}`);
    taskInput.value = "";
  });

  taskInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      taskBtn.click();
    }
  });
}
