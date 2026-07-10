(function () {
  const CONTACT_PROMPT = "If you'd like to get in touch, please leave your email and job description using the contact form below, and PD will be notified.";

  function getSessionId() {
    let sessionId = sessionStorage.getItem("pd_chat_session_id");
    if (!sessionId) {
      sessionId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      sessionStorage.setItem("pd_chat_session_id", sessionId);
    }
    return sessionId;
  }

  function apiBase() {
    const configuredUrl = typeof CHATBOT_API_URL !== "undefined" ? CHATBOT_API_URL : window.CHATBOT_API_URL;
    return (configuredUrl || "").replace(/\/+$/, "");
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function chatMessages() {
    return document.getElementById("chatMessages");
  }

  function appendMessage(role, content, extraClass) {
    const messages = chatMessages();
    if (!messages) return null;

    const message = document.createElement("div");
    message.className = `chat-msg ${role}${extraClass ? ` ${extraClass}` : ""}`;
    message.innerHTML = escapeHtml(content).replace(/\n/g, "<br>");
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
  }

  function setSending(isSending) {
    const input = document.getElementById("chatInput");
    const button = document.getElementById("chatSend");
    if (input) input.disabled = isSending;
    if (button) button.disabled = isSending;
  }

  function shouldShowContactForm(reply) {
    return /contact form/i.test(reply);
  }

  function showContactForm() {
    const messages = chatMessages();
    if (!messages || document.getElementById("chatContactForm")) return;

    const form = document.createElement("form");
    form.id = "chatContactForm";
    form.className = "chat-contact-form";
    form.innerHTML = `
      <input class="chat-contact-input" id="chatContactEmail" type="email" placeholder="Email" required>
      <textarea class="chat-contact-input" id="chatContactJob" rows="3" placeholder="Job description or note"></textarea>
      <button class="chat-contact-submit" type="submit">Submit</button>
      <div class="chat-contact-status" id="chatContactStatus"></div>
    `;

    form.addEventListener("submit", submitContactForm);
    messages.appendChild(form);
    messages.scrollTop = messages.scrollHeight;
  }

  async function submitContactForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const status = document.getElementById("chatContactStatus");
    const email = document.getElementById("chatContactEmail").value.trim();
    const jobDescription = document.getElementById("chatContactJob").value.trim();
    const submit = form.querySelector("button");

    if (status) status.textContent = "Sending...";
    if (submit) submit.disabled = true;

    try {
      const response = await fetch(`${apiBase()}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, jobDescription, sessionId: getSessionId() })
      });

      if (!response.ok) {
        throw new Error("Contact request failed");
      }

      if (status) status.textContent = "Thanks. PD will be notified.";
      form.querySelectorAll("input, textarea, button").forEach((element) => {
        element.disabled = true;
      });
    } catch (error) {
      if (status) status.textContent = "Sorry, the contact form could not be sent right now.";
      if (submit) submit.disabled = false;
    }
  }

  window.toggleChat = function toggleChat() {
    const panel = document.getElementById("chatPanel");
    const hint = document.getElementById("chatHint");
    if (panel) panel.classList.toggle("open");
    if (hint) hint.style.display = "none";
  };

  window.sendChat = async function sendChat() {
    const input = document.getElementById("chatInput");
    const message = input ? input.value.trim() : "";
    if (!message) return;

    appendMessage("user", message);
    input.value = "";
    setSending(true);
    const typing = appendMessage("bot", "Typing...", "typing");

    try {
      const response = await fetch(`${apiBase()}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, sessionId: getSessionId() })
      });

      if (!response.ok) {
        throw new Error("Chat request failed");
      }

      const data = await response.json();
      const reply = data.reply || "Sorry, I could not generate a response right now.";
      if (typing) typing.remove();
      appendMessage("bot", reply);

      if (shouldShowContactForm(reply)) {
        showContactForm();
      }
    } catch (error) {
      if (typing) typing.remove();
      appendMessage("bot", "Sorry, I'm having trouble right now.");
    } finally {
      setSending(false);
      if (input) input.focus();
    }
  };

  function ensureChatStyles() {
    if (document.getElementById("chatSharedStyles")) return;

    const panel = document.querySelector(".chat-panel");
    if (panel && getComputedStyle(panel).position === "fixed") return;

    const style = document.createElement("style");
    style.id = "chatSharedStyles";
    style.textContent = `
      .chat-bubble { position: fixed; bottom: 28px; right: 28px; z-index: 100; display: flex; align-items: center; gap: 10px; }
      .chat-fab-btn { width: 72px; height: 72px; border-radius: 50%; background: var(--quant-ai); color: var(--bg); display: flex; align-items: center; justify-content: center; cursor: pointer; box-shadow: 0 4px 24px rgba(78,205,196,.35); transition: transform .2s; border: none; position: relative; }
      .chat-fab-btn:hover { transform: scale(1.08); }
      .chat-pulse { position: absolute; inset: -4px; border-radius: 50%; background: var(--quant-ai); opacity: .35; animation: pulse 2.5s infinite; z-index: -1; }
      @keyframes pulse { 0% { transform: scale(1); opacity: .3; } 70% { transform: scale(1.4); opacity: 0; } 100% { transform: scale(1); opacity: 0; } }
      .chat-hint { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 18px; font-size: 15px; font-weight: 500; color: var(--text); white-space: nowrap; box-shadow: 0 4px 16px rgba(0,0,0,.3); cursor: pointer; }
      .chat-hint .arrow { color: var(--quant-ai); }
      .chat-panel { position: fixed; bottom: 104px; right: 28px; width: 360px; max-height: 500px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; display: none; flex-direction: column; z-index: 100; overflow: hidden; }
      .chat-panel.open { display: flex; }
      .chat-header { padding: 14px 16px; border-bottom: 1px solid var(--border); font-weight: 600; display: flex; justify-content: space-between; align-items: center; }
      .chat-messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; max-height: 340px; }
      .chat-msg { padding: 8px 12px; border-radius: 8px; font-size: 14px; max-width: 85%; word-wrap: break-word; line-height: 1.4; }
      .chat-msg.user { background: var(--quant-ai); color: var(--bg); align-self: flex-end; }
      .chat-msg.bot { background: rgba(255,255,255,.06); color: var(--text); align-self: flex-start; }
      .chat-msg.typing { color: var(--muted); }
      .chat-input-area { padding: 12px; border-top: 1px solid var(--border); display: flex; gap: 8px; }
      .chat-input { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; color: var(--text); font-size: 14px; outline: none; min-width: 0; }
      .chat-input:focus { border-color: var(--quant-ai); }
      .chat-send, .chat-contact-submit { padding: 8px 16px; background: var(--quant-ai); color: var(--bg); border: none; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 14px; }
      .chat-send:hover, .chat-contact-submit:hover { background: #6ee7d7; }
      .chat-send:disabled, .chat-contact-submit:disabled { opacity: .5; cursor: not-allowed; }
      .chat-contact-form { align-self: stretch; display: flex; flex-direction: column; gap: 8px; padding: 10px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.04); }
      .chat-contact-input { width: 100%; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; color: var(--text); font-size: 14px; outline: none; resize: vertical; }
      .chat-contact-input:focus { border-color: var(--quant-ai); }
      .chat-contact-status { min-height: 16px; color: var(--muted); font-size: 12px; }
      @media (max-width: 768px) { .chat-hint { display: none; } .chat-panel { width: calc(100vw - 32px); right: 16px; } }
    `;
    document.head.appendChild(style);
  }

  ensureChatStyles();
})();
