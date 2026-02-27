const chatBox =
    document.getElementById('chat-box');
const userInput =
    document.getElementById('user-input');
const sendButton =
    document.getElementById('send-button');
const sidebarToggle =
    document.getElementById('sidebar-toggle');
const modeToggle =
    document.getElementById('mode-toggle-checkbox');
const sidebar =
    document.querySelector('.sidebar');

modeToggle.addEventListener('change', () => {
    document.body.classList.toggle('dark-mode');
    document.body.classList.toggle('light-mode');
});

sendButton.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        sendMessage();
    }
});

document.addEventListener('DOMContentLoaded', function () {
    const newConversationBtn =
            document.getElementById('new-conversation-btn');
    const conversationContent =
            document.querySelector('.conversation-content');
    const sidebarToggle =
            document.getElementById('sidebar-toggle');
    const chatContainer =
            document.querySelector('.chat-container');

    sidebarToggle.addEventListener('click', function () {
        const sidebar = document.querySelector('.sidebar');
        sidebar.classList.toggle('collapsed');

        if (sidebar.classList.contains('collapsed')) {
            chatContainer.style.width = '100%';
            chatContainer.style.marginLeft = '0';
            sidebarToggle.style.left = '12px';
        } else {
            chatContainer.style.width = 'calc(100% - 260px)';
            chatContainer.style.marginLeft = '260px';
            sidebarToggle.style.left = '220px';
        }
    });
    newConversationBtn.addEventListener('click', function () {
        conversationContent.textContent = "New Conversation Started!";
    });

});

function sendMessage() {
    const message = userInput.value.trim();
    if (message !== '') {
        appendMessage('user', message);
        userInput.value = '';
    }
}

function appendMessage(sender, message) {
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.style.display = 'none';

    const role = sender === 'user' ? 'user' : 'assistant';

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
        body.innerHTML = `<p>${message}</p>`;
    } else {
        body.textContent = message;
    }

    row.appendChild(icon);
    row.appendChild(body);
    chatBox.appendChild(row);
    chatBox.scrollTop = chatBox.scrollHeight;
}
