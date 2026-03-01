// ── Config ───────────────────────────────────────────────────────────────────
const API_BASE = 'http://localhost:8000';
const WS_BASE  = 'ws://localhost:8000';

let MODELS = [];

// ── State ────────────────────────────────────────────────────────────────────
let sessionId    = null;
let currentModel = 'openai/gpt-4.1-mini';
let ws           = null;
let isWaiting    = false;   // true while waiting for assistant response

// ── DOM refs ─────────────────────────────────────────────────────────────────
const chatBox          = document.getElementById('chat-box');
const userInput        = document.getElementById('user-input');
const sendButton       = document.getElementById('send-button');
const sidebarToggle    = document.getElementById('sidebar-toggle');
const modeToggle       = document.getElementById('mode-toggle-checkbox');
const newConversationBtn = document.getElementById('new-conversation-btn');
const modelDropBtn     = document.getElementById('modelDropBtn');
const modelDropdown    = document.getElementById('modelDropdown');
const modelSearchInput = document.getElementById('modelSearchInput');
const sessionsList     = document.getElementById('sessionsList');
const sessionTitle     = document.getElementById('sessionTitle');
const modelBadge       = document.getElementById('modelBadge');
const wsStatus         = document.getElementById('wsStatus');
const emptyState       = document.getElementById('empty-state');
const toast            = document.getElementById('toast');
const chatContainer    = document.querySelector('.chat-container');
const sidebar          = document.querySelector('.sidebar');

// ── Init ─────────────────────────────────────────────────────────────────────
// Fetches available models, creates a new session, and loads past sessions.
async function init() {
    await fetchModels();
    newSession();
    loadSessions();
}

// Populate the model dropdown from the /models API endpoint
async function fetchModels() {
    try {
        const res = await fetch(`${API_BASE}/models`);
        const data = await res.json();
        MODELS = data.models ?? [];
    } catch(e) {
        console.warn('Could not load models from server', e);
        MODELS = ['openai/gpt-4.1-mini'];
    }
    populateModels();
}

// Render clickable model items inside the searchable dropdown
function populateModels() {
    modelDropdown.querySelectorAll('.model-item').forEach(el => el.remove());

    MODELS.forEach(m => {
        const item = document.createElement('a');
        item.className = 'model-item';
        if (m === currentModel) item.classList.add('active');
        item.textContent = m;
        item.addEventListener('click', (e) => {
            e.preventDefault();
            currentModel = m;
            const shortName = m.split('/')[1] ?? m;
            modelDropBtn.textContent = shortName;
            modelBadge.textContent = shortName;
            modelDropdown.classList.remove('show');
            modelSearchInput.value = '';
            highlightActiveModel();
            changeModel();
        });
        modelDropdown.appendChild(item);
    });

    modelDropBtn.textContent = (currentModel.split('/')[1] ?? currentModel);
}

// Mark the currently selected model in the dropdown list
function highlightActiveModel() {
    modelDropdown.querySelectorAll('.model-item').forEach(el => {
        el.classList.toggle('active', el.textContent === currentModel);
    });
}

// ── Session management ───────────────────────────────────────────────────────

function generateUUID() {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
        (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

// Create a brand-new chat session and open a WebSocket for it
function newSession() {
    if (ws) { ws.close(); ws = null; }
    sessionId = generateUUID();
    currentModel = currentModel || 'openai/gpt-4.1-mini';
    clearMessages();
    sessionTitle.childNodes[0].textContent = 'New Chat';
    modelBadge.textContent = currentModel.split('/')[1] ?? currentModel;
    connectWebSocket();
}

// Restore a previous session: fetch its history, update UI, reconnect WS
async function loadSession(id) {
    if (ws) { ws.close(); ws = null; }
    sessionId = id;
    clearMessages();

    try {
        const res = await fetch(`${API_BASE}/history/${id}`);
        const data = await res.json();
        const msgs = data.messages ?? [];
        msgs.forEach(m => appendMessage(m.role, m.content));

        const sRes = await fetch(`${API_BASE}/session/${id}`);
        const sData = await sRes.json();
        if (sData.model) {
            currentModel = sData.model;
            modelDropBtn.textContent = currentModel.split('/')[1] ?? currentModel;
            modelBadge.textContent = currentModel.split('/')[1] ?? currentModel;
            highlightActiveModel();
        }
        sessionTitle.childNodes[0].textContent = sData.title ?? 'Chat';
    } catch(e) {
        showToast('Failed to load session');
    }

    connectWebSocket();
    highlightSession(id);
}

// Fetch all sessions from the API and render them in the sidebar
async function loadSessions() {
    try {
        const res = await fetch(`${API_BASE}/sessions`);
        const data = await res.json();
        renderSessions(data.sessions ?? []);
    } catch(e) {
        console.warn('Could not load sessions', e);
    }
}

// Build the sidebar session list DOM from an array of session objects
function renderSessions(sessions) {
    sessionsList.innerHTML = '';
    sessions.forEach(s => {
        const item = document.createElement('div');
        item.className = 'session-item';
        item.dataset.id = s.session_id;
        if (s.session_id === sessionId) item.classList.add('active');

        const label = document.createElement('span');
        label.textContent = s.title || 'Untitled';

        const delBtn = document.createElement('button');
        delBtn.className = 'btn-delete-session';
        delBtn.title = 'Delete';
        delBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        delBtn.addEventListener('click', e => { e.stopPropagation(); deleteSession(s.session_id); });

        item.appendChild(label);
        item.appendChild(delBtn);
        item.addEventListener('click', () => loadSession(s.session_id));
        sessionsList.appendChild(item);
    });
}

// Toggle the .active class on the currently selected session in the sidebar
function highlightSession(id) {
    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === id);
    });
}

// Delete a session via API; if it's the current one, start a new session
async function deleteSession(id) {
    try {
        await fetch(`${API_BASE}/session/${id}`, { method: 'DELETE' });
        if (id === sessionId) newSession();
        loadSessions();
    } catch(e) {
        showToast('Failed to delete session');
    }
}

// ── WebSocket ────────────────────────────────────────────────────────────────
// Opens a WS connection for the current session to receive streamed responses.
function connectWebSocket() {
    setWsStatus('connecting');
    ws = new WebSocket(`${WS_BASE}/ws/${sessionId}`);

    ws.onopen = () => {
        setWsStatus('connected');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'message') {
            removeTypingIndicator();
            appendMessage(data.role, data.content);
            isWaiting = false;
            sendButton.disabled = false;

            // Server may send an auto-generated title after the first reply
            if (data.title) {
                sessionTitle.childNodes[0].textContent = data.title;
                loadSessions();
            }
        } else if (data.type === 'error') {
            removeTypingIndicator();
            showToast(data.message || 'Something went wrong');
            isWaiting = false;
            sendButton.disabled = false;
        } else if (data.type === 'title_update') {
            sessionTitle.childNodes[0].textContent = data.title;
            loadSessions();
        }
    };

    ws.onerror = () => setWsStatus('disconnected');

    ws.onclose = () => {
        setWsStatus('disconnected');
        sendButton.disabled = true;
        if (sessionId) setTimeout(connectWebSocket, 2000);
    };
}

// Update the coloured dot in the header to reflect WS state
function setWsStatus(state) {
    wsStatus.className = `ws-status ${state}`;
    wsStatus.title = state.charAt(0).toUpperCase() + state.slice(1);
}

// ── Messaging ────────────────────────────────────────────────────────────────

// Send the user's message via REST, then wait for the WS response
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text || isWaiting) return;

    appendMessage('user', text);
    userInput.value = '';
    showTypingIndicator();
    isWaiting = true;
    sendButton.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/send-message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                content: text,
                model: currentModel
            })
        });
        const data = await res.json();
        if (data.status !== 'ok') {
            removeTypingIndicator();
            showToast(data.message || 'Failed to send message');
            isWaiting = false;
            sendButton.disabled = false;
        }
    } catch(e) {
        removeTypingIndicator();
        showToast('Failed to reach server');
        isWaiting = false;
        sendButton.disabled = false;
    }
}

// Append a user or assistant message row to the chat box.
// Assistant content is rendered as markdown via marked.js.
function appendMessage(role, content) {
    if (emptyState) emptyState.style.display = 'none';

    const row = document.createElement('div');
    row.className = `msg-row ${role}`;

    const icon = document.createElement('div');
    icon.className = 'msg-icon';
    if (role === 'user') {
        icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z"/></svg>';
    } else {
        icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2z"/></svg>';
    }

    const body = document.createElement('div');
    body.className = 'msg-body';
    if (role === 'assistant') {
        body.innerHTML = marked.parse(content);
    } else {
        body.textContent = content;
    }

    row.appendChild(icon);
    row.appendChild(body);
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
}

// Show three bouncing dots while waiting for the assistant reply
function showTypingIndicator() {
    const row = document.createElement('div');
    row.className = 'msg-row assistant';
    row.id = 'typingRow';

    const icon = document.createElement('div');
    icon.className = 'msg-icon';
    icon.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2z"/></svg>';

    const body = document.createElement('div');
    body.className = 'msg-body';
    body.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';

    row.appendChild(icon);
    row.appendChild(body);
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function removeTypingIndicator() {
    const el = document.getElementById('typingRow');
    if (el) el.remove();
}

// Reset the chat box to its initial empty state
function clearMessages() {
    chatBox.innerHTML = '';
    chatBox.appendChild(emptyState);
    emptyState.style.display = '';
}

// ── UI helpers ───────────────────────────────────────────────────────────────

// Flash a short message at the bottom of the screen
function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// Persist model change for the current session on the server
async function changeModel() {
    try {
        await fetch(`${API_BASE}/session/${sessionId}/change-model?model=${encodeURIComponent(currentModel)}`, {
            method: 'POST'
        });
    } catch(e) {
        console.warn('Failed to update model', e);
    }
}

// ── Event listeners ──────────────────────────────────────────────────────────

sendButton.addEventListener('click', sendMessage);

userInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        sendMessage();
    }
});

// Toggle between light and dark mode
modeToggle.addEventListener('change', () => {
    document.body.classList.toggle('dark-mode');
    document.body.classList.toggle('light-mode');
});

// Expand / collapse sidebar and adjust chat layout accordingly
sidebarToggle.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');

    const chatHeader = document.querySelector('.chat-header');
    if (sidebar.classList.contains('collapsed')) {
        chatContainer.style.width = '100%';
        chatContainer.style.marginLeft = '0';
        sidebarToggle.style.left = '12px';
        chatHeader.style.paddingLeft = '56px';
    } else {
        chatContainer.style.width = 'calc(100% - 260px)';
        chatContainer.style.marginLeft = '260px';
        sidebarToggle.style.left = '220px';
        chatHeader.style.paddingLeft = '20px';
    }
});

newConversationBtn.addEventListener('click', () => {
    newSession();
    loadSessions();
});

// Toggle the searchable model dropdown open/closed
modelDropBtn.addEventListener('click', () => {
    modelDropdown.classList.toggle('show');
    if (modelDropdown.classList.contains('show')) {
        modelSearchInput.value = '';
        modelDropdown.querySelectorAll('.model-item').forEach(el => el.style.display = '');
        modelSearchInput.focus();
    }
});

// Filter model items as the user types in the search box
modelSearchInput.addEventListener('keyup', function () {
    const filter = this.value.toUpperCase();
    modelDropdown.querySelectorAll('.model-item').forEach(item => {
        item.style.display = item.textContent.toUpperCase().includes(filter) ? '' : 'none';
    });
});

// Close the dropdown when clicking anywhere outside of it
document.addEventListener('click', (e) => {
    if (!e.target.closest('.model-dropdown')) {
        modelDropdown.classList.remove('show');
    }
});

// ── Boot ─────────────────────────────────────────────────────────────────────
init();
