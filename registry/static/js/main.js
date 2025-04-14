document.addEventListener('DOMContentLoaded', function () {
    // Navigation
    const navLinks = document.querySelectorAll('nav a');

    // Only set up views that exist in the DOM initially
    const views = {
        dashboard: document.getElementById('dashboard-view'),
        agentDetails: document.getElementById('agent-details-view'),
        // These will be created dynamically, so start with null
        sharedMemory: null,
        agentChat: null
    };

    // Initialize views that exist
    for (const view in views) {
        if (views[view] && view !== 'dashboard') {
            views[view].style.display = 'none';
        }
    }

    document.getElementById('nav-dashboard').addEventListener('click', function (e) {
        e.preventDefault();
        showView('dashboard');
        updateActiveNav(this);
    });

    document.getElementById('nav-memory').addEventListener('click', function (e) {
        e.preventDefault();
        // Create memory view if it doesn't exist yet
        if (!views.sharedMemory) {
            const memoryView = document.createElement('div');
            memoryView.id = 'shared-memory-view';
            memoryView.style.display = 'none';
            document.querySelector('.container').appendChild(memoryView);
            views.sharedMemory = memoryView;
        }
        showView('sharedMemory');
        updateActiveNav(this);
        loadSharedMemory();
    });

    document.getElementById('nav-chat').addEventListener('click', function (e) {
        e.preventDefault();
        // Can't show chat view directly - need an agent to chat with
        updateActiveNav(this);
        // If we don't have an agent yet, show a message
        alert('Please select an agent to chat with from the dashboard');
        showView('dashboard');
    });

    function showView(viewName) {
        for (const view in views) {
            if (views[view]) {
                views[view].style.display = view === viewName ? 'block' : 'none';
            }
        }
    }

    function updateActiveNav(clickedLink) {
        navLinks.forEach(link => link.classList.remove('active'));
        clickedLink.classList.add('active');
    }

    // Agent details
    const viewDetailsBtns = document.querySelectorAll('.view-details-btn');
    viewDetailsBtns.forEach(btn => {
        btn.addEventListener('click', function () {
            const agentId = this.getAttribute('data-agent-id');
            loadAgentDetails(agentId);
        });
    });

    // Chat buttons
    const chatBtns = document.querySelectorAll('.chat-btn');
    chatBtns.forEach(btn => {
        btn.addEventListener('click', function () {
            const agentId = this.getAttribute('data-agent-id');
            openChat(agentId);
        });
    });

    // Back to dashboard button
    if (document.getElementById('back-to-dashboard')) {
        document.getElementById('back-to-dashboard').addEventListener('click', function () {
            showView('dashboard');
            updateActiveNav(document.getElementById('nav-dashboard'));
        });
    }

    // Tab switching
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', function () {
            const tabName = this.getAttribute('data-tab');

            // Update tab active state
            tabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            // Show corresponding content
            const tabContents = document.querySelectorAll('.tab-content');
            tabContents.forEach(content => {
                content.classList.remove('active');
                if (content.getAttribute('data-tab') === tabName) {
                    content.classList.add('active');
                }
            });
        });
    });

    // Load agent details
    function loadAgentDetails(agentId) {
        fetch(`/agents/${agentId}`)
            .then(response => response.json())
            .then(agent => {
                document.getElementById('detail-agent-name').textContent = agent.name;

                // Fill in agent info tab
                const infoContent = document.querySelector('[data-tab="info"].tab-content');
                infoContent.innerHTML = `
                    <div class="detail-section">
                        <h3>Basic Information</h3>
                        <div class="agent-meta">
                            <span class="meta-label">ID:</span>
                            <span class="meta-value">${agent.id}</span>
                            
                            <span class="meta-label">Description:</span>
                            <span class="meta-value">${agent.description}</span>
                            
                            <span class="meta-label">Version:</span>
                            <span class="meta-value">${agent.version}</span>
                            
                            <span class="meta-label">Last Update:</span>
                            <span class="meta-value">${new Date(agent.last_update * 1000).toLocaleString()}</span>
                        </div>
                    </div>
                    
                    <div class="detail-section">
                        <h3>Capabilities</h3>
                        <div class="capability-list">
                            ${agent.capabilities.map(cap => `
                                <span class="capability-tag">${cap}</span>
                            `).join('')}
                        </div>
                    </div>
                    
                    <div class="detail-section">
                        <h3>Model Information</h3>
                        <div class="agent-meta">
                            <span class="meta-label">Type:</span>
                            <span class="meta-value">${agent.model_info.type}</span>
                            
                            <span class="meta-label">Provider:</span>
                            <span class="meta-value">${agent.model_info.provider}</span>
                        </div>
                    </div>
                    
                    <div class="detail-section">
                        <h3>Technical Details</h3>
                        <div class="agent-meta">
                            <span class="meta-label">Protocols:</span>
                            <span class="meta-value">${agent.protocols.join(', ')}</span>
                            
                            <span class="meta-label">Interfaces:</span>
                            <span class="meta-value">${JSON.stringify(agent.interfaces)}</span>
                            
                            <span class="meta-label">Endpoints:</span>
                            <span class="meta-value">${JSON.stringify(agent.endpoints)}</span>
                        </div>
                    </div>
                `;

                // Load peers tab
                loadAgentPeers(agentId);

                // Show agent details view
                showView('agentDetails');

                // Update navigation
                navLinks.forEach(link => link.classList.remove('active'));
            });
    }

    // Load agent peers
    function loadAgentPeers(agentId) {
        fetch(`/agents/${agentId}/peers`)
            .then(response => response.json())
            .then(data => {
                const peersContent = document.querySelector('[data-tab="peers"].tab-content');

                if (!data.peers || data.peers.length === 0) {
                    peersContent.innerHTML = '<p>No peers found for this agent.</p>';
                    return;
                }

                let peerListHtml = '<ul class="peer-list">';
                data.peers.forEach(peerId => {
                    peerListHtml += `
                        <li class="peer-item">
                            <span class="peer-name">${peerId}</span>
                            <button class="btn btn-secondary view-peer-btn" data-peer-id="${peerId}">View</button>
                        </li>
                    `;
                });
                peerListHtml += '</ul>';

                peersContent.innerHTML = peerListHtml;

                // Add event listeners to view peer buttons
                const viewPeerBtns = peersContent.querySelectorAll('.view-peer-btn');
                viewPeerBtns.forEach(btn => {
                    btn.addEventListener('click', function () {
                        const peerId = this.getAttribute('data-peer-id');
                        loadAgentDetails(peerId);
                    });
                });
            })
            .catch(error => {
                console.error('Error fetching peers:', error);
                const peersContent = document.querySelector('[data-tab="peers"].tab-content');
                peersContent.innerHTML = '<p>Error loading peers: ' + error.message + '</p>';
            });
    }

    // Open chat with agent
    function openChat(agentId) {
        fetch(`/agents/${agentId}`)
            .then(response => response.json())
            .then(agent => {
                // Create chat view if it doesn't exist
                if (!views.agentChat) {
                    const chatView = document.createElement('div');
                    chatView.id = 'agent-chat-view';
                    chatView.style.display = 'none';
                    document.querySelector('.container').appendChild(chatView);
                    views.agentChat = chatView;
                }

                // Update chat view
                views.agentChat.innerHTML = `
                    <div class="chat-container">
                        <div class="chat-header">
                            <h2>Chat with ${agent.name}</h2>
                        </div>
                        <div class="chat-messages" id="chat-messages">
                            <!-- Messages will be loaded here -->
                        </div>
                        <div class="chat-input">
                            <input type="text" id="message-input" placeholder="Type your message...">
                            <button id="send-message-btn">Send</button>
                        </div>
                    </div>
                    <div class="agent-actions" style="text-align: center; margin-top: 1rem;">
                        <button class="btn btn-secondary" id="back-from-chat">Back to Dashboard</button>
                    </div>
                `;

                // Add event listener to back button
                document.getElementById('back-from-chat').addEventListener('click', function () {
                    showView('dashboard');
                    updateActiveNav(document.getElementById('nav-dashboard'));
                });

                // Load chat history
                loadChatHistory(agentId);

                // Add event listener to send button
                document.getElementById('send-message-btn').addEventListener('click', function () {
                    sendMessage(agentId);
                });

                // Add event listener to input for Enter key
                document.getElementById('message-input').addEventListener('keypress', function (e) {
                    if (e.key === 'Enter') {
                        sendMessage(agentId);
                    }
                });

                // Show chat view
                showView('agentChat');

                // Update navigation
                navLinks.forEach(link => link.classList.remove('active'));
                document.getElementById('nav-chat').classList.add('active');
            });
    }

    // Load chat history
    function loadChatHistory(agentId) {
        fetch(`/agents/${agentId}/chat/history`)
            .then(response => response.json())
            .then(data => {
                const messagesContainer = document.getElementById('chat-messages');
                if (!messagesContainer) return;

                messagesContainer.innerHTML = '';

                if (!data.messages || data.messages.length === 0) {
                    messagesContainer.innerHTML = '<p>No messages yet. Start a conversation!</p>';
                    return;
                }

                data.messages.forEach(message => {
                    const userMessage = document.createElement('div');
                    userMessage.className = 'message message-user';
                    userMessage.innerHTML = `
                        <div class="message-content">${message.user}</div>
                        <div class="message-time">${new Date(message.timestamp * 1000).toLocaleString()}</div>
                    `;
                    messagesContainer.appendChild(userMessage);

                    const agentMessage = document.createElement('div');
                    agentMessage.className = 'message message-agent';
                    agentMessage.innerHTML = `
                        <div class="message-content">${message.agent}</div>
                        <div class="message-time">${new Date(message.timestamp * 1000).toLocaleString()}</div>
                    `;
                    messagesContainer.appendChild(agentMessage);
                });

                // Scroll to bottom
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            })
            .catch(error => {
                console.error('Error loading chat history:', error);
                const messagesContainer = document.getElementById('chat-messages');
                if (messagesContainer) {
                    messagesContainer.innerHTML = '<p>Error loading chat history.</p>';
                }
            });
    }

    // Send message to agent
    function sendMessage(agentId) {
        const messageInput = document.getElementById('message-input');
        if (!messageInput) return;

        const message = messageInput.value.trim();

        if (!message) return;

        // Clear input
        messageInput.value = '';

        // Add message to UI immediately
        const messagesContainer = document.getElementById('chat-messages');
        if (!messagesContainer) return;

        const userMessage = document.createElement('div');
        userMessage.className = 'message message-user';
        userMessage.innerHTML = `
            <div class="message-content">${message}</div>
            <div class="message-time">${new Date().toLocaleString()}</div>
        `;
        messagesContainer.appendChild(userMessage);

        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // Send message to agent
        fetch(`/agents/${agentId}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                text: message
            })
        })
            .then(response => response.json())
            .then(data => {
                // Add agent response to UI
                const agentMessage = document.createElement('div');
                agentMessage.className = 'message message-agent';
                agentMessage.innerHTML = `
                <div class="message-content">${data.response}</div>
                <div class="message-time">${new Date().toLocaleString()}</div>
            `;
                messagesContainer.appendChild(agentMessage);

                // Scroll to bottom
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            })
            .catch(error => {
                console.error('Error sending message:', error);

                // Add error message to UI
                const errorMessage = document.createElement('div');
                errorMessage.className = 'message message-error';
                errorMessage.innerHTML = `
                <div class="message-content">Error: ${error.message}</div>
                <div class="message-time">${new Date().toLocaleString()}</div>
            `;
                messagesContainer.appendChild(errorMessage);

                // Scroll to bottom
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            });
    }

    // Load shared memory
    function loadSharedMemory() {
        // Create shared memory view if it doesn't exist
        if (!views.sharedMemory) {
            const memoryView = document.createElement('div');
            memoryView.id = 'shared-memory-view';
            memoryView.style.display = 'none';
            document.querySelector('.container').appendChild(memoryView);
            views.sharedMemory = memoryView;
        }

        fetch('/shared-memory')
            .then(response => response.json())
            .then(data => {
                let memoryHtml = `
                    <div class="memory-container">
                        <div class="memory-header">
                            <h2>Shared Memory</h2>
                        </div>
                        <div class="memory-list">
                `;

                if (Object.keys(data.memory).length === 0) {
                    memoryHtml += '<p>No shared memory entries found.</p>';
                } else {
                    for (const [key, entry] of Object.entries(data.memory)) {
                        memoryHtml += `
                            <div class="memory-item">
                                <div class="memory-key">${key}</div>
                                <div class="memory-value">${JSON.stringify(entry.value, null, 2)}</div>
                                <div class="memory-meta">
                                    <span>Owner: ${entry.owner}</span>
                                    <span>Updated: ${new Date(entry.timestamp * 1000).toLocaleString()}</span>
                                </div>
                            </div>
                        `;
                    }
                }

                memoryHtml += `
                        </div>
                        <div class="memory-actions">
                            <h3>Add New Memory Entry</h3>
                            <div class="memory-form">
                                <fieldset>
                                    <legend>Memory Entry Details</legend>
                                    
                                    <div class="form-group">
                                        <label for="memory-key">Key:</label>
                                        <div class="input-with-help">
                                            <input type="text" id="memory-key" placeholder="e.g., agent_settings_123">
                                            <div class="help-text">A unique identifier for this memory entry</div>
                                        </div>
                                    </div>
                                    
                                    <div class="form-group">
                                        <label for="memory-owner">Owner:</label>
                                        <div class="input-with-help">
                                            <input type="text" id="memory-owner" placeholder="e.g., web-ui or agent.agents.local">
                                            <div class="help-text">Entity that created/owns this memory (optional)</div>
                                        </div>
                                    </div>
                                    
                                    <div class="form-group value-group">
                                        <label for="memory-value">Value (JSON):</label>
                                        <div class="textarea-container">
                                            <textarea id="memory-value" rows="8" placeholder='e.g., {"key": "some_key", "data": [1, 2, 3]}'></textarea>
                                            <div class="json-status" id="json-status"></div>
                                        </div>
                                        <div class="help-text">
                                            Enter valid JSON data. Simple values like strings or numbers are also accepted.
                                            <details>
                                                <summary>Show Example</summary>
                                                <pre class="json-example">{
  "key": "some_key",
  "value": {"any": "json-serializable value"},
  "owner": "agent1.agents.local"
}</pre>
                                            </details>
                                        </div>
                                    </div>
                                </fieldset>
                                
                                <div class="form-actions">
                                    <button id="clear-memory-form" class="btn btn-secondary">Clear</button>
                                    <button id="add-memory-btn" class="btn btn-primary">Add Memory</button>
                                </div>
                            </div>
                        </div>
                        <div class="agent-actions" style="text-align: center; margin-top: 1rem;">
                            <button class="btn btn-secondary" id="back-from-memory">Back to Dashboard</button>
                        </div>
                    </div>
                `;

                views.sharedMemory.innerHTML = memoryHtml;

                // Add event listener to back button
                document.getElementById('back-from-memory').addEventListener('click', function () {
                    showView('dashboard');
                    updateActiveNav(document.getElementById('nav-dashboard'));
                });

                // Add event listener to memory value field to validate JSON
                const memoryValueInput = document.getElementById('memory-value');
                const jsonStatus = document.getElementById('json-status');

                if (memoryValueInput && jsonStatus) {
                    memoryValueInput.addEventListener('input', function () {
                        validateJson(this.value);
                    });

                    // Initial validation
                    validateJson(memoryValueInput.value);
                }

                // Add event listener to clear button
                const clearButton = document.getElementById('clear-memory-form');
                if (clearButton) {
                    clearButton.addEventListener('click', function () {
                        document.getElementById('memory-key').value = '';
                        document.getElementById('memory-owner').value = '';
                        document.getElementById('memory-value').value = '';
                        document.getElementById('json-status').innerHTML = '';
                        document.getElementById('json-status').className = '';
                    });
                }

                // Add event listener to add memory button
                document.getElementById('add-memory-btn').addEventListener('click', addMemoryEntry);

                // Initialize example dropdown
                const exampleToggle = document.querySelector('details summary');
                if (exampleToggle) {
                    exampleToggle.addEventListener('click', function (e) {
                        e.preventDefault();
                        const details = this.parentNode;
                        details.toggleAttribute('open');
                    });
                }
            })
            .catch(error => {
                console.error('Error loading shared memory:', error);
                if (views.sharedMemory) {
                    views.sharedMemory.innerHTML = '<p>Error loading shared memory: ' + error.message + '</p>';
                }
            });
    }

    // Add memory entry
    function addMemoryEntry() {
        const keyInput = document.getElementById('memory-key');
        const valueInput = document.getElementById('memory-value');
        const ownerInput = document.getElementById('memory-owner');

        if (!keyInput || !valueInput) return;

        const key = keyInput.value.trim();
        const valueText = valueInput.value.trim();
        const owner = ownerInput ? ownerInput.value.trim() : '' || 'registry-ui';

        if (!key || !valueText) {
            alert('Please enter both key and value');
            return;
        }

        // Try to parse value as JSON
        let value;
        try {
            value = JSON.parse(valueText);
        } catch (e) {
            // If not valid JSON, use as string
            value = valueText;
        }

        fetch('/shared-memory', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                key: key,
                value: value,
                owner: owner
            })
        })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // Reload shared memory
                    loadSharedMemory();
                } else {
                    alert('Error adding memory entry: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error adding memory entry:', error);
                alert('Error adding memory entry: ' + error.message);
            });
    }

    // Auto-refresh
    setInterval(function () {
        // Refresh the currently visible view
        if (views.dashboard && views.dashboard.style.display !== 'none') {
            // Refresh agent status indicators
            updateAgentStatuses();
        } else if (views.sharedMemory && views.sharedMemory.style.display !== 'none') {
            loadSharedMemory();
        }
    }, 30000); // Every 30 seconds

    // Validate JSON for memory entry
    function validateJson(text) {
        const jsonStatus = document.getElementById('json-status');
        if (!jsonStatus) return;

        if (!text.trim()) {
            jsonStatus.innerHTML = '';
            jsonStatus.className = '';
            return;
        }

        try {
            JSON.parse(text);
            jsonStatus.innerHTML = 'Valid JSON ✓';
            jsonStatus.className = 'status-valid';
        } catch (e) {
            // If not obviously JSON, don't show error for simple values
            if (text.trim().match(/^["{\[\d]/) || text.includes(':')) {
                jsonStatus.innerHTML = 'Invalid JSON ✗<br><small>' + e.message + '</small>';
                jsonStatus.className = 'status-invalid';
            } else {
                // For simple strings, numbers, etc.
                jsonStatus.innerHTML = 'Simple value (will be stored as string)';
                jsonStatus.className = 'status-info';
            }
        }
    }

    // Update agent status indicators
    function updateAgentStatuses() {
        fetch('/agents')
            .then(response => response.json())
            .then(data => {
                const now = Date.now() / 1000;
                data.agents.forEach(agent => {
                    const agentCard = document.querySelector(`.agent-card[data-agent-id="${agent.id}"]`);
                    if (agentCard) {
                        const statusEl = agentCard.querySelector('.agent-status');
                        if (statusEl) {
                            if (now - agent.last_update < 120) { // 2 minutes
                                statusEl.textContent = 'Online';
                                statusEl.className = 'agent-status status-online';
                            } else {
                                statusEl.textContent = 'Offline';
                                statusEl.className = 'agent-status status-offline';
                            }
                        }
                    }
                });
            })
            .catch(error => console.error('Error updating agent statuses:', error));
    }
});
