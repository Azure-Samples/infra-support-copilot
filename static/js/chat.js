/**
 * Chat functionality for the RAG application.
 * 
 * This JavaScript handles the client-side functionality of the RAG application:
 * - Manages the chat UI (sending messages, displaying responses)
 * - Communicates with the FastAPI backend via fetch API
 * - Handles citations and displays them in a modal
 * - Manages error states and loading indicators
 * 
 * The chat interface supports:
 * 1. Free-form text input
 * 2. Quick-select question buttons
 * 3. Interactive citations from source documents
 * 4. Responsive design for various screen sizes
 */
document.addEventListener('DOMContentLoaded', function() {
    // Language settings
    let currentLanguage = localStorage.getItem('language') || 'ja';
    
    // Elements
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    const chatHistory = document.getElementById('chat-history');
    const chatContainer = document.getElementById('chat-container');
    const loadingIndicator = document.getElementById('loading-indicator');
    const errorContainer = document.getElementById('error-container');
    const errorMessage = document.getElementById('error-message');
    const promptSuggestionContainer = document.getElementById('prompt-suggestion');
    const languageToggle = document.getElementById('language-toggle');
    
    // Centered form elements
    const centeredInputForm = document.getElementById('centered-input-form');
    const centeredChatForm = document.getElementById('centered-chat-form');
    const centeredChatInput = document.getElementById('centered-chat-input');
    const centeredSendButton = document.getElementById('centered-send-button');
    const centeredErrorContainer = document.getElementById('centered-error-container');
    const centeredErrorMessage = document.getElementById('centered-error-message');

    // Quick response buttons
    const promptButtons = document.querySelectorAll('#prompt-suggestion .prompt-btn');

    // Chat history array
    let messages = [];
    
    // Event listeners
    chatForm.addEventListener('submit', handleChatSubmit);
    chatInput.addEventListener('keydown', handleKeyDown);
    
    // Centered form event listeners
    centeredChatForm.addEventListener('submit', handleCenteredChatSubmit);
    centeredChatInput.addEventListener('keydown', handleCenteredKeyDown);

    // Language toggle event listener
    if (languageToggle) {
        languageToggle.addEventListener('click', () => {
            currentLanguage = currentLanguage === 'ja' ? 'en' : 'ja';
            localStorage.setItem('language', currentLanguage);
            updateLanguage();
        });
    }

    // Attach handlers for prompt buttons (fills input with fixed sentence)
    if (promptButtons && promptButtons.length > 0) {
        promptButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const text = btn.getAttribute(`data-text-${currentLanguage}`) || btn.textContent.trim();
                const activeInput = getCurrentActiveInput();
                activeInput.value = text;
                activeInput.focus();
            });
        });
    }

    // Initialize language
    updateLanguage();
    
    // Hide prompt suggestions if history already has items (e.g., persisted state)
    updatePromptSuggestionVisibility();
    
    /**
     * Updates the language for all text elements
     */
    function updateLanguage() {
        // Update all elements with data-ja and data-en attributes
        document.querySelectorAll('[data-ja]').forEach(element => {
            const text = element.getAttribute(`data-${currentLanguage}`);
            if (text) {
                if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
                    element.placeholder = text;
                } else {
                    element.textContent = text;
                }
            }
        });

        // Update prompt button labels and data-text attributes
        document.querySelectorAll('.prompt-btn').forEach(btn => {
            const text = btn.getAttribute(`data-${currentLanguage}`);
            if (text) {
                btn.textContent = text;
                btn.setAttribute('aria-label', text);
            }
        });

        // Update language toggle button text
        if (languageToggle) {
            const toggleSpan = languageToggle.querySelector('span');
            if (toggleSpan) {
                const toggleText = toggleSpan.getAttribute(`data-${currentLanguage}`);
                if (toggleText) {
                    toggleSpan.textContent = toggleText;
                }
            }
        }

        // Update selectable list titles if they exist
        updateSelectableListTitles();
    }

    /**
     * Updates selectable list titles based on current language
     */
    function updateSelectableListTitles() {
        const tableTitle = currentLanguage === 'ja' ? 'どのテーブルを検索しますか？' : 'Which tables do you want to search?';
        const columnTitle = currentLanguage === 'ja' ? 'どのカラムを検索しますか？' : 'Which columns do you want to search?';
        const sqlMethodTitle = currentLanguage === 'ja' ? 'どのようにSQL Databaseを検索しますか？' : 'How would you like to search the SQL Database?';
        const confirmText = currentLanguage === 'ja' ? '決定' : 'Confirm';

        document.querySelectorAll('.selectable-options .fw-semibold').forEach(title => {
            if (title.textContent.includes('テーブル') || title.textContent.includes('tables')) {
                title.textContent = tableTitle;
            } else if (title.textContent.includes('カラム') || title.textContent.includes('columns')) {
                title.textContent = columnTitle;
            } else if (title.textContent.includes('SQL Database') || title.textContent.includes('どのようにSQL')) {
                title.textContent = sqlMethodTitle;
            }
        });

        // Update radio button labels
        document.querySelectorAll('.selectable-options .form-check-label').forEach(label => {
            const input = document.querySelector(`#${label.getAttribute('for')}`);
            if (input && input.getAttribute('data-ja') && input.getAttribute('data-en')) {
                const jaText = input.getAttribute('data-ja');
                const enText = input.getAttribute('data-en');
                label.textContent = currentLanguage === 'ja' ? jaText : enText;
            }
        });

        document.querySelectorAll('.selectable-options .btn').forEach(btn => {
            if (btn.textContent === '決定' || btn.textContent === 'Confirm') {
                btn.textContent = confirmText;
            }
        });
    }

    /**
     * Get the currently active input field based on visibility
     */
    function getCurrentActiveInput() {
        return centeredInputForm.classList.contains('d-none') ? chatInput : centeredChatInput;
    }
    
    /**
     * Get the currently active error container based on visibility
     */
    function getCurrentErrorContainer() {
        return centeredInputForm.classList.contains('d-none') ? errorContainer : centeredErrorContainer;
    }
    
    /**
     * Get the currently active error message element based on visibility
     */
    function getCurrentErrorMessage() {
        return centeredInputForm.classList.contains('d-none') ? errorMessage : centeredErrorMessage;
    }

    /**
     * Creates the assistant avatar element with the provided SVG icon
     */
    function createAssistantAvatar() {
        const avatar = document.createElement('div');
        avatar.className = 'avatar-badge me-2';
        avatar.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
                <g fill="none" stroke="#000" stroke-linecap="round" stroke-linejoin="round" stroke-width="2">
                    <rect width="20" height="14" x="2" y="9" rx="4"/>
                    <circle cx="12" cy="3" r="2"/>
                    <path d="M12 5v4m-3 8v-2m6 0v2"/>
                </g>
            </svg>
        `;
        return avatar;
    }

    function updatePromptSuggestionVisibility() {
        if (!promptSuggestionContainer) return;
        const hasAnyMessage = chatHistory && chatHistory.children && chatHistory.children.length > 0;
        if (hasAnyMessage) {
            promptSuggestionContainer.classList.add('d-none');
            centeredInputForm.classList.add('d-none');
            document.body.classList.remove('empty-chat');
        } else {
            promptSuggestionContainer.classList.remove('d-none');
            centeredInputForm.classList.remove('d-none');
            document.body.classList.add('empty-chat');
        }
    }

    /**
     * Handles form submission when the user sends a message from main form
     */
    function handleChatSubmit(e) {
        e.preventDefault();
        const query = chatInput.value.trim();
        if (query && !isLoading()) {
            sendMessage(query);
        }
    }
    
    /**
     * Handles form submission when the user sends a message from centered form
     */
    function handleCenteredChatSubmit(e) {
        e.preventDefault();
        const query = centeredChatInput.value.trim();
        if (query && !isLoading()) {
            sendMessage(query);
        }
    }
    
    /**
     * Handles sending a message when Enter key is pressed in main input
     */
    function handleKeyDown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const query = chatInput.value.trim();
            if (query && !isLoading()) {
                sendMessage(query);
            }
        }
    }
    
    /**
     * Handles sending a message when Enter key is pressed in centered input
     */
    function handleCenteredKeyDown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const query = centeredChatInput.value.trim();
            if (query && !isLoading()) {
                sendMessage(query);
            }
        }
    }
    
    /**
     * Checks if a request is currently loading
     */
    function isLoading() {
        return !loadingIndicator.classList.contains('d-none');
    }
    
    /**
     * Displays a user message in the chat interface
     */
    function addUserMessage(text) {
        // Remove any placeholder if present
        if (chatHistory.querySelector('.text-center')) {
            chatHistory.innerHTML = '';
        }
        if (!(text.startsWith(";;SQL;;") || text.startsWith(";;EXECUTE;;") || text.startsWith(";;SQL_QUERY_OPTION;;"))) {
            // Create user message DOM directly
            const wrapper = document.createElement('div');
            wrapper.className = 'd-flex mb-4 justify-content-end align-items-end';
            const card = document.createElement('div');
            card.className = 'card user-card';
            card.style.maxWidth = '80%';
            const cardBody = document.createElement('div');
            cardBody.className = 'card-body';
            const messageContent = document.createElement('div');
            messageContent.className = 'message-content';
            messageContent.style.lineHeight = '1.5';
            
            // Convert markdown to HTML for user messages too
            let htmlContent;
            try {
                // Configure marked options
                marked.setOptions({
                    breaks: true,
                    gfm: true,
                    headerIds: false,
                    mangle: false
                });
                
                htmlContent = marked.parse(text);
            } catch (error) {
                console.warn('Markdown parsing failed for user message, falling back to plain text:', error);
                htmlContent = text.replace(/\n/g, '<br>');
            }
            
            messageContent.innerHTML = htmlContent;
            cardBody.appendChild(messageContent);
            card.appendChild(cardBody);
            wrapper.appendChild(card);
            
            chatHistory.appendChild(wrapper);
            scrollToBottom();
            updatePromptSuggestionVisibility();
        }
    }
    
    /**
     * Displays an assistant message with citations in the chat interface
     * 
     * This function:
     * 1. Creates the HTML for the assistant's message
     * 2. Processes any citations returned from Azure AI Search
     * 3. Converts citation references [doc1], [doc2], etc. into clickable badges
     * 4. Sets up event handlers for citation badge clicks
     * 5. Adds the message to the chat history
     */
    function addAssistantMessage(content, citations, conversation_id) {
        // Create assistant message DOM directly
        const wrapper = document.createElement('div');
        // Keep items on one line and align at the top so the avatar stays left of the bubble
        wrapper.className = 'd-flex mb-4 align-items-start flex-nowrap';
        wrapper.style.width = '100%';
        const card = document.createElement('div');
        card.className = 'card assistant-card';
        // Allow the bubble to shrink within the flex row to avoid wrapping under the avatar
        card.style.maxWidth = '80%';
        card.style.flexShrink = '1';
        card.style.minWidth = '0';
        const cardBody = document.createElement('div');
        cardBody.className = 'card-body';
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        messageContent.style.lineHeight = '1.5';
        // Prevent long words/URLs from forcing the bubble wider than available space
        messageContent.style.wordBreak = 'break-word';
        messageContent.style.overflowWrap = 'anywhere';

        const messageId = 'msg-' + Date.now();

        // Detect special selectable list format: ";;SELECTABLE;;item1,item2,..."
        const sqlQueryOptionPrefix = ';;SQL_QUERY_OPTION;;';
        const isSqlQueryOption = typeof content === 'string' && content.trim().startsWith(sqlQueryOptionPrefix);

        if (isSqlQueryOption) {
            const items = [
                {
                    ja: "手動でテーブル・項目を選択する",
                    en: "Manually select tables and items"
                },
                {
                    ja: "自動でテーブル・項目を選択する", 
                    en: "Automatically select tables and items"
                }
            ];
            // Build checkbox list UI
            const container = document.createElement('div');
            container.className = 'selectable-options';

            // Create collapsible header
            const header = document.createElement('div');
            header.className = 'collapsible-header d-flex justify-content-between align-items-center mb-2 p-2';
            header.style.cursor = 'pointer';
            header.style.backgroundColor = '#f8f9fa';
            header.style.borderRadius = '0.375rem';
            header.style.border = '1px solid #dee2e6';

            const title = document.createElement('span');
            title.className = 'fw-semibold';
            title.textContent = currentLanguage === 'ja' ? 'どのようにSQL Databaseを検索しますか？' : 'How would you like to search the SQL Database?';

            const toggleIcon = document.createElement('span');
            toggleIcon.className = 'toggle-icon';
            toggleIcon.innerHTML = '▼';
            toggleIcon.style.transition = 'transform 0.2s ease';

            header.appendChild(title);
            header.appendChild(toggleIcon);
            container.appendChild(header);

            // Create collapsible content
            const content = document.createElement('div');
            content.className = 'collapsible-content';
            content.style.display = 'block'; // Start expanded

            const list = document.createElement('div');
            list.className = 'd-flex flex-column gap-2';

            items.forEach((item, idx) => {
                const id = `${messageId}-opt-${idx + 1}`;
                const row = document.createElement('div');
                row.className = 'form-check';

                const input = document.createElement('input');
                input.type = 'radio';
                input.className = 'form-check-input';
                input.id = id;
                input.name = `${messageId}-sql-query-option`; // 同じnameでグループ化
                input.value = item.ja; // 常に日本語の値を保存（バックエンドとの互換性のため）
                input.setAttribute('data-ja', item.ja);
                input.setAttribute('data-en', item.en);

                const lbl = document.createElement('label');
                lbl.className = 'form-check-label';
                lbl.setAttribute('for', id);
                lbl.textContent = item[currentLanguage];

                row.appendChild(input);
                row.appendChild(lbl);
                list.appendChild(row);
            });

            content.appendChild(list);

            // Action buttons (apply selection to input, clear selection)
            const actions = document.createElement('div');
            actions.className = 'd-flex gap-2 mt-3 justify-content-end';

            let selectColumnInput = '';

            const applyBtn = document.createElement('button');
            applyBtn.type = 'button';
            applyBtn.className = 'btn btn-dark btn-sm';
            // Ensure pure black styling regardless of theme
            applyBtn.style.backgroundColor = '#000';
            applyBtn.style.borderColor = '#000';
            applyBtn.style.color = '#fff';
            applyBtn.textContent = currentLanguage === 'ja' ? '決定' : 'Confirm';

            applyBtn.disabled = true;
            list.addEventListener('change', () => {
                const anyChecked = list.querySelectorAll('input[type="radio"]:checked').length > 0;
                applyBtn.disabled = !anyChecked;
            });

            applyBtn.addEventListener('click', () => {
                const selected = Array.from(list.querySelectorAll('input[type="radio"]:checked'))
                    .map(el => el.value)
                    .filter(Boolean);
                if (selected.length > 0) {
                    const selectedMethod = selected[0] == "手動でテーブル・項目を選択する" ? "manual" : "auto"; 
                    selectColumnInput = ';;SQL_QUERY_OPTION;;' + selectedMethod; // 1つだけ選択
                    sendMessage(selectColumnInput, conversation_id);
                    scrollToBottom();
                }
            });

            actions.appendChild(applyBtn);
            content.appendChild(actions);
            container.appendChild(content);

            // Add toggle functionality
            header.addEventListener('click', () => {
                const isCollapsed = content.style.display === 'none';
                content.style.display = isCollapsed ? 'block' : 'none';
                toggleIcon.style.transform = isCollapsed ? 'rotate(0deg)' : 'rotate(-90deg)';
                toggleIcon.innerHTML = isCollapsed ? '▼' : '▶';
            });

            messageContent.appendChild(container);
            cardBody.appendChild(messageContent);
            card.appendChild(cardBody);
            card.setAttribute('id', messageId);
            // No citations processing for selectable lists

            // Add avatar next to the message card (assistant on the left)
            const avatar = createAssistantAvatar();
            wrapper.appendChild(avatar);
            wrapper.appendChild(card);
            chatHistory.appendChild(wrapper);

            updatePromptSuggestionVisibility();
            scrollToBottom();
            return; // Done for selectable content
        }

        // Detect special selectable list format: ";;SELECTABLE;;item1,item2,..."
        const selectablePrefix = ';;SELECTABLE;;';
        const isSelectable = typeof content === 'string' && content.trim().startsWith(selectablePrefix);

        if (isSelectable) {
            const itemsRaw = content.trim().slice(selectablePrefix.length).trim();
            const items = itemsRaw.split(',').map(s => s.trim()).filter(Boolean);

            if (items.length > 0) {
                // Build checkbox list UI
                const container = document.createElement('div');
                container.className = 'selectable-options';

                // Create collapsible header
                const header = document.createElement('div');
                header.className = 'collapsible-header d-flex justify-content-between align-items-center mb-2 p-2';
                header.style.cursor = 'pointer';
                header.style.backgroundColor = '#f8f9fa';
                header.style.borderRadius = '0.375rem';
                header.style.border = '1px solid #dee2e6';

                const title = document.createElement('span');
                title.className = 'fw-semibold';
                title.textContent = currentLanguage === 'ja' ? 'どのテーブルを検索しますか？' : 'Which tables do you want to search?';

                const toggleIcon = document.createElement('span');
                toggleIcon.className = 'toggle-icon';
                toggleIcon.innerHTML = '▼';
                toggleIcon.style.transition = 'transform 0.2s ease';

                header.appendChild(title);
                header.appendChild(toggleIcon);
                container.appendChild(header);

                // Create collapsible content
                const content = document.createElement('div');
                content.className = 'collapsible-content';
                content.style.display = 'block'; // Start expanded

                const list = document.createElement('div');
                list.className = 'd-flex flex-column gap-2';

                items.forEach((label, idx) => {
                    const id = `${messageId}-opt-${idx + 1}`;
                    const row = document.createElement('div');
                    row.className = 'form-check';

                    const input = document.createElement('input');
                    input.type = 'checkbox';
                    input.className = 'form-check-input';
                    input.id = id;
                    input.value = label;

                    const lbl = document.createElement('label');
                    lbl.className = 'form-check-label';
                    lbl.setAttribute('for', id);
                    lbl.textContent = label;

                    row.appendChild(input);
                    row.appendChild(lbl);
                    list.appendChild(row);
                });

                content.appendChild(list);

                // Action buttons (apply selection to input, clear selection)
                const actions = document.createElement('div');
                actions.className = 'd-flex gap-2 mt-3 justify-content-end';

                let selectTableInput = '';

                const applyBtn = document.createElement('button');
                applyBtn.type = 'button';
                applyBtn.className = 'btn btn-dark btn-sm';
                // Ensure pure black styling regardless of theme
                applyBtn.style.backgroundColor = '#000';
                applyBtn.style.borderColor = '#000';
                applyBtn.style.color = '#fff';
                applyBtn.textContent = currentLanguage === 'ja' ? '決定' : 'Confirm';

                applyBtn.disabled = true;
                list.addEventListener('change', () => {
                    const anyChecked = list.querySelectorAll('input[type="checkbox"]:checked').length > 0;
                    applyBtn.disabled = !anyChecked;
                });
                applyBtn.addEventListener('click', () => {
                    const selected = Array.from(list.querySelectorAll('input[type="checkbox"]:checked'))
                        .map(el => el.value)
                        .filter(Boolean);
                    selectTableInput = ';;SQL;;' +selected.join(',');
                    sendMessage(selectTableInput, conversation_id);
                });

                actions.appendChild(applyBtn);
                content.appendChild(actions);
                container.appendChild(content);

                // Add toggle functionality
                header.addEventListener('click', () => {
                    const isCollapsed = content.style.display === 'none';
                    content.style.display = isCollapsed ? 'block' : 'none';
                    toggleIcon.style.transform = isCollapsed ? 'rotate(0deg)' : 'rotate(-90deg)';
                    toggleIcon.innerHTML = isCollapsed ? '▼' : '▶';
                });

                messageContent.appendChild(container);
                cardBody.appendChild(messageContent);
                card.appendChild(cardBody);
                card.setAttribute('id', messageId);
                // No citations processing for selectable lists

                // Add avatar next to the message card (assistant on the left)
                const avatar = createAssistantAvatar();
                wrapper.appendChild(avatar);
                wrapper.appendChild(card);
                chatHistory.appendChild(wrapper);

                updatePromptSuggestionVisibility();
                scrollToBottom();
                return; // Done for selectable content
            }
            // If no items parsed, fall through to default rendering
        }

        // Detect special selectable list format: ";;SELECTABLE;;item1,item2,..."
        const columnsPrefix = ';;COLUMNS;;';
        const isColumns = typeof content === 'string' && content.trim().startsWith(columnsPrefix);

        if (isColumns) {
            const itemsRaw = content.trim().slice(columnsPrefix.length).trim();
            // Expect multi-line payload; ignore first line, parse the rest as 'a|b' -> 'a.b'
            const lines = itemsRaw.split(/\r?\n/).map(s => s.trim());
            const dataLines = lines.filter(Boolean).slice(2); // ignore first non-empty line
            const items = [];
            for (const line of dataLines) {
                const parts = line.split('|').map(s => s.trim());
                if (parts.length >= 2 && parts[0] && parts[1]) {
                    items.push(`${parts[0]}.${parts[1]}`);
                }
            }

            if (items.length > 0) {
                // Build checkbox list UI
                const container = document.createElement('div');
                container.className = 'selectable-options';

                // Create collapsible header
                const header = document.createElement('div');
                header.className = 'collapsible-header d-flex justify-content-between align-items-center mb-2 p-2';
                header.style.cursor = 'pointer';
                header.style.backgroundColor = '#f8f9fa';
                header.style.borderRadius = '0.375rem';
                header.style.border = '1px solid #dee2e6';

                const title = document.createElement('span');
                title.className = 'fw-semibold';
                title.textContent = currentLanguage === 'ja' ? 'どのカラムを検索しますか？' : 'Which columns do you want to search?';

                const toggleIcon = document.createElement('span');
                toggleIcon.className = 'toggle-icon';
                toggleIcon.innerHTML = '▼';
                toggleIcon.style.transition = 'transform 0.2s ease';

                header.appendChild(title);
                header.appendChild(toggleIcon);
                container.appendChild(header);

                // Create collapsible content
                const content = document.createElement('div');
                content.className = 'collapsible-content';
                content.style.display = 'block'; // Start expanded

                const list = document.createElement('div');
                list.className = 'd-flex flex-column gap-2';

                items.forEach((label, idx) => {
                    const id = `${messageId}-opt-${idx + 1}`;
                    const row = document.createElement('div');
                    row.className = 'form-check';

                    const input = document.createElement('input');
                    input.type = 'checkbox';
                    input.className = 'form-check-input';
                    input.id = id;
                    input.value = label;

                    const lbl = document.createElement('label');
                    lbl.className = 'form-check-label';
                    lbl.setAttribute('for', id);
                    lbl.textContent = label;

                    row.appendChild(input);
                    row.appendChild(lbl);
                    list.appendChild(row);
                });

                content.appendChild(list);

                // Action buttons (apply selection to input, clear selection)
                const actions = document.createElement('div');
                actions.className = 'd-flex gap-2 mt-3 justify-content-end';

                let selectColumnInput = '';

                const applyBtn = document.createElement('button');
                applyBtn.type = 'button';
                applyBtn.className = 'btn btn-dark btn-sm';
                // Ensure pure black styling regardless of theme
                applyBtn.style.backgroundColor = '#000';
                applyBtn.style.borderColor = '#000';
                applyBtn.style.color = '#fff';
                applyBtn.textContent = currentLanguage === 'ja' ? '決定' : 'Confirm';

                applyBtn.disabled = true;
                list.addEventListener('change', () => {
                    const anyChecked = list.querySelectorAll('input[type="checkbox"]:checked').length > 0;
                    applyBtn.disabled = !anyChecked;
                });

                applyBtn.addEventListener('click', () => {
                    const selected = Array.from(list.querySelectorAll('input[type="checkbox"]:checked'))
                        .map(el => el.value)
                        .filter(Boolean);
                    selectColumnInput = ';;EXECUTE;;' +selected.join(',');
                    sendMessage(selectColumnInput, conversation_id);
                    scrollToBottom();
                });

                actions.appendChild(applyBtn);
                content.appendChild(actions);
                container.appendChild(content);

                // Add toggle functionality
                header.addEventListener('click', () => {
                    const isCollapsed = content.style.display === 'none';
                    content.style.display = isCollapsed ? 'block' : 'none';
                    toggleIcon.style.transform = isCollapsed ? 'rotate(0deg)' : 'rotate(-90deg)';
                    toggleIcon.innerHTML = isCollapsed ? '▼' : '▶';
                });

                messageContent.appendChild(container);
                cardBody.appendChild(messageContent);
                card.appendChild(cardBody);
                card.setAttribute('id', messageId);
                // No citations processing for selectable lists

                // Add avatar next to the message card (assistant on the left)
                const avatar = createAssistantAvatar();
                wrapper.appendChild(avatar);
                wrapper.appendChild(card);
                chatHistory.appendChild(wrapper);

                updatePromptSuggestionVisibility();
                scrollToBottom();
                return; // Done for selectable content
            }
            // If no items parsed, fall through to default rendering
        }

    // Handle citations
    let formattedContent = content || '';
        const messageCitations = {};
        if (citations && citations.length > 0) {
            const pattern = /\[doc(\d+)\]/g;
            formattedContent = formattedContent.replace(pattern, (match, index) => {
                const idx = parseInt(index);
                if (idx > 0 && idx <= citations.length) {
                    const citation = citations[idx - 1];
                    const citationData = JSON.stringify({
                        title: citation.title || '',
                        content: citation.content || '',
                        filePath: citation.filePath || '',
                        url: citation.url || ''
                    });
                    messageCitations[idx] = citationData;
                    return `<a class="badge citation-badge rounded-pill" data-message-id="${messageId}" data-index="${idx}">${idx}</a>`;
                }
                return match;
            });
        }
        
        // Convert markdown to HTML using marked.js
        let htmlContent;
        try {
            // Configure marked options for better rendering
            marked.setOptions({
                breaks: true,        // Support line breaks
                gfm: true,          // GitHub Flavored Markdown
                headerIds: false,   // Disable header IDs
                mangle: false       // Don't mangle autolinks
            });
            
            // Parse markdown to HTML
            htmlContent = marked.parse(formattedContent);
        } catch (error) {
            console.warn('Markdown parsing failed, falling back to plain text:', error);
            htmlContent = formattedContent.replace(/\n/g, '<br>');
        }
        
        messageContent.innerHTML = htmlContent;
        cardBody.appendChild(messageContent);
        card.appendChild(cardBody);
        card.setAttribute('id', messageId);
        card.setAttribute('data-citations', JSON.stringify(messageCitations));
        
    // Add avatar next to the message card (assistant on the left)
    const avatar = createAssistantAvatar();
        wrapper.appendChild(avatar);
        wrapper.appendChild(card);
        chatHistory.appendChild(wrapper);
    // Ensure suggestions remain hidden once messages exist
    updatePromptSuggestionVisibility();
        // Add click listeners for citation badges
        setTimeout(() => {
            const badges = messageContent.querySelectorAll('.badge[data-index]');
            badges.forEach(badge => {
                badge.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const messageId = this.getAttribute('data-message-id');
                    const idx = this.getAttribute('data-index');
                    const messageElement = document.getElementById(messageId);
                    const messageCitations = JSON.parse(messageElement.getAttribute('data-citations') || '{}');
                    const citationData = JSON.parse(messageCitations[idx]);
                    showCitationModal(citationData);
                });
            });
        }, 100);
        scrollToBottom();
    }
    
    /**
     * Shows a modal with citation details
     */
    function showCitationModal(citationData) {
        // Remove any existing modal
        const existingOverlay = document.querySelector('.citation-overlay');
        if (existingOverlay) {
            existingOverlay.remove();
        }
        
        // Format the citation content for better display with Markdown support
        let formattedContent = citationData.content || 'No content available';
        
        // Remove URLs from markdown links, keeping only the title text
        // Pattern matches [title](url) and replaces with just title
        formattedContent = formattedContent.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
        
        let htmlContent;
        
        try {
            // Configure marked options for citation content
            marked.setOptions({
                breaks: true,
                gfm: true,
                headerIds: false,
                mangle: false
            });
            
            // Parse markdown to HTML
            htmlContent = marked.parse(formattedContent);
        } catch (error) {
            console.warn('Markdown parsing failed for citation content, falling back to plain text:', error);
            htmlContent = formattedContent.replace(/\n/g, '<br>');
        }
        
        // Create overlay and modal
        const overlay = document.createElement('div');
        overlay.className = 'citation-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-labelledby', 'citation-modal-title');
        
        overlay.innerHTML = `
            <div class="citation-modal">
                <div class="citation-modal-header">
                    <h5 class="citation-modal-title" id="citation-modal-title">${citationData.title || 'Citation'}</h5>
                    <button type="button" class="citation-close-button" aria-label="Close">&times;</button>
                </div>
                <div class="citation-modal-body">
                    <div class="citation-content markdown-content">${htmlContent}</div>
                    ${citationData.filePath ? `<div class="citation-source mt-3"><strong>Source:</strong> ${citationData.filePath}</div>` : ''}
                    ${citationData.url ? `<div class="citation-url mt-2"><strong>URL:</strong> <a href="${citationData.url}" target="_blank" rel="noopener noreferrer">${citationData.url}</a></div>` : ''}
                </div>
            </div>
        `;
        
        // Add overlay to the document
        document.body.appendChild(overlay);
        
        // Set focus on the modal container for keyboard navigation
        const modal = overlay.querySelector('.citation-modal');
        modal.focus();
        
        // Handle close button click
        const closeButton = overlay.querySelector('.citation-close-button');
        closeButton.addEventListener('click', () => {
            overlay.remove();
        });
        
        // Close modal when clicking outside
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) {
                overlay.remove();
            }
        });
        
        // Close modal on escape key
        document.addEventListener('keydown', function closeOnEscape(e) {
            if (e.key === 'Escape') {
                overlay.remove();
                document.removeEventListener('keydown', closeOnEscape);
            }
        });
    }
    
    /**
     * Displays an error message
     */
    function showError(text) {
        const errorMsg = getCurrentErrorMessage();
        const errorCont = getCurrentErrorContainer();
        errorMsg.textContent = text;
        errorCont.classList.remove('d-none');
    }
    
    /**
     * Hides the error message
     */
    function hideError() {
        errorContainer.classList.add('d-none');
        centeredErrorContainer.classList.add('d-none');
    }
    
    /**
     * Shows the loading indicator
     */
    function showLoading() {
        loadingIndicator.classList.remove('d-none');
        sendButton.disabled = true;
        centeredSendButton.disabled = true;
        // Disable all prompt buttons while loading
        document.querySelectorAll('#prompt-suggestion .prompt-btn').forEach(btn => btn.disabled = true);
    }
    
    /**
     * Hides the loading indicator
     */
    function hideLoading() {
        loadingIndicator.classList.add('d-none');
        sendButton.disabled = false;
        centeredSendButton.disabled = false;
        // Enable all prompt buttons after loading
        document.querySelectorAll('#prompt-suggestion .prompt-btn').forEach(btn => btn.disabled = false);
    }
    
    /**
     * Scrolls the chat container to the bottom
     */
    function scrollToBottom() {
        setTimeout(() => {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }, 50);
    }
    
    /**
     * Sends a user message to the server for RAG processing
     * 
     * This function:
     * 1. Adds the user message to the UI
     * 2. Sends the entire conversation history to the FastAPI backend
     * 3. Processes the response from Azure OpenAI enhanced with Azure AI Search results
     * 4. Extracts any citations from the context
     * 5. Handles errors gracefully with user-friendly messages
     */
    function sendMessage(text, conversation_id="") {
        hideError();
        
        // Add user message to UI
        addUserMessage(text);
        
        // Clear input fields
        chatInput.value = '';
        centeredChatInput.value = '';
        
        // Add user message to chat history
        const userMessage = {
            role: 'user',
            content: text
        };
        messages.push(userMessage);
        
        // Show loading indicator
        showLoading();

        // Send request to server
        fetch('/api/chat/completion', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                messages: messages,
                conversation_id: conversation_id
            })
        })
        .then(response => {
            if (!response.ok) {
                // Try to parse the error response
                return response.json().then(errorData => {
                    throw new Error(errorData.message || `HTTP error! Status: ${response.status}`);
                }).catch(e => {
                    // If can't parse JSON, use generic error
                    throw new Error(`HTTP error! Status: ${response.status}`);
                });
            }
            // Log raw response for debugging
            return response.json();
        })
        .then(data => {
            hideLoading();
            
            if (data.error) {
                // Handle API error
                showError(data.message || 'An error occurred');
                return;
            }
            
            const choice = data.choices && data.choices.length > 0 ? data.choices[0] : null;
            if (!choice || !choice.message || !choice.message.content) {
                showError('No answer received from the AI service.');
                return;
            }
            
            // Get message data
            const message = choice.message;
            const content = message.content;
            const metadata = message.metadata || {};
            const conversation_id = metadata.conversation_id || null;
            
            // Extract citations from context
            const citations = message.context?.citations || [];
            
            // Add assistant message to UI
            addAssistantMessage(content, citations, conversation_id);
            
            // Add assistant message to chat history
            const assistantMessage = {
                role: 'assistant',
                content: content
            };
            messages.push(assistantMessage);
        })
        .catch(error => {
            hideLoading();
            showError(`Error: ${error.message}`);
            console.error('Error:', error);
        });
    }
});
