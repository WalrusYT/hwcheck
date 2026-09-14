function renderMathIn(el) {
  if (window.renderMathInElement) {
    window.renderMathInElement(el, { delimiters: window.MATH_DELIMITERS, throwOnError: false });
  }
}

function initHomeworkChat(cardId, messagesId, formId, inputId) {
  const card = document.getElementById(cardId);
  const messagesEl = document.getElementById(messagesId);
  const formEl = document.getElementById(formId);
  const inputEl = document.getElementById(inputId);
  if (!card || !formEl) return;

  const chatUrl = card.dataset.chatUrl;

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

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      formEl.requestSubmit();
    }
  });

  formEl.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = inputEl.value.trim();
    if (!message) return;

    addBubble("user", message);
    inputEl.value = "";

    const typing = addBubble("bot typing", "…");

    try {
      const res = await fetch(chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      const data = await res.json();
      typing.remove();

      if (!res.ok) {
        addBubble("bot error", data.error || "Something went wrong.");
        return;
      }
      addBubble("bot", data.reply);
    } catch (err) {
      typing.remove();
      addBubble("bot error", "Could not reach the server.");
    }
  });
}
