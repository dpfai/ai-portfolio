(() => {
  if (document.getElementById('chatBubble')) return;

  document.body.insertAdjacentHTML('beforeend', `
    <div class="chat-bubble" id="chatBubble">
      <div class="chat-hint" id="chatHint" onclick="toggleChat()">
        Ask PD’s AI assistant <span class="arrow">→</span>
      </div>
      <button class="chat-fab-btn" onclick="toggleChat()" aria-label="Open PD’s AI assistant">
        <span class="chat-pulse"></span>
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
    </div>
    <div class="chat-panel" id="chatPanel">
      <div class="chat-header">
        <span>PD’s AI Assistant</span>
        <button onclick="toggleChat()" aria-label="Close PD’s AI assistant" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:18px">×</button>
      </div>
      <div class="chat-messages" id="chatMessages">
        <div class="chat-msg bot">Ask me about AdEval Causal, AI Trading Arena, PD's measurement experience, or the methods behind these projects.</div>
      </div>
      <div class="chat-input-area">
        <input type="text" class="chat-input" id="chatInput" placeholder="Ask about a project or method..." onkeypress="if(event.key==='Enter')sendChat()">
        <button class="chat-send" id="chatSend" onclick="sendChat()">Send</button>
      </div>
    </div>
  `);

  window.CHATBOT_API_URL = 'https://pd-lab-chatbot.dpfstat.workers.dev';
  const script = document.createElement('script');
  script.src = 'chat.js?v=20260726-1';
  document.body.appendChild(script);

  window.openPortfolioChat = function openPortfolioChat(question) {
    const panel = document.getElementById('chatPanel');
    if (panel && !panel.classList.contains('open')) {
      if (typeof window.toggleChat === 'function') window.toggleChat();
      else panel.classList.add('open');
    }
    const input = document.getElementById('chatInput');
    if (input && question) input.value = question;
    if (input) input.focus();
  };
})();
