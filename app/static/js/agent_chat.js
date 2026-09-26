document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('agent-form');
    if (!chatForm) return;

    chatForm.addEventListener('submit', async function(e) {
        e.preventDefault();

        const inputField = document.getElementById('user_query');
        const message = inputField.value.trim();
        if (!message) return;

        appendChatBubble('user', 'You: ' + message);
        inputField.value = '';

        const loadingId = appendChatBubble('assistant', 'Bank Buddy is typing...');

        try {
            const response = await fetch('/agent/send',  async function send() {
    const msg = input.value.trim();
    if (!msg) return;
    addBubble('user', msg);
    input.value = '';
    const loading = addBubble('assistant', 'Bank Buddy is typing...');

    try {
      const r = await fetch('/agent/send', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: msg})
      });
      const data = await r.json();
      loading.innerHTML = '<strong style="color:#6C63FF;">Bank Buddy:</strong> ' +
                          escapeHtml(data.response || data.error || 'No response.');
    } catch (e) {
      loading.innerText = 'Error reaching backend.';
    }
    chatBox.scrollTop = chatBox.scrollHeight;
  });

            const contentType = response.headers.get('content-type') || '';

            if (!contentType.includes('application/json')) {
                updateChatBubble(
                    loadingId,
                    'Error: session expired or not logged in. Please log in again.'
                );
                return;
            }

            const data = await response.json();

            if (data.response) {
                updateChatBubble(loadingId, 'Bank Buddy: ' + data.response);
            } else if (data.error) {
                updateChatBubble(loadingId, 'Error: ' + data.error);
            } else {
                updateChatBubble(loadingId, 'Error: unknown response from server.');
            }
        } catch (err) {
            updateChatBubble(loadingId, 'Failed to reach backend. Please try again.');
        }
    });
});

function appendChatBubble(role, text) {
    const chatContainer = document.getElementById('chat-history-container');
    if (!chatContainer) return null;

    const id = 'msg-' + Math.random().toString(36).substr(2, 9);
    const html = `<div id="${id}" class="chat-bubble ${role}">${escapeHtml(text)}</div>`;
    chatContainer.insertAdjacentHTML('beforeend', html);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return id;
}

function updateChatBubble(id, newText) {
    const element = document.getElementById(id);
    if (element) element.innerText = newText;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}