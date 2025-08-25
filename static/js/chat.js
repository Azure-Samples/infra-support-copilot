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
    // Elements
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    const chatHistory = document.getElementById('chat-history');
    const chatContainer = document.getElementById('chat-container');
    const loadingIndicator = document.getElementById('loading-indicator');
    const errorContainer = document.getElementById('error-container');
    const errorMessage = document.getElementById('error-message');
    

    
    // Quick response buttons
    const btnPersonalInfo = document.getElementById('btn-personal-info');
    const btnWarranty = document.getElementById('btn-warranty');
    const btnCompany = document.getElementById('btn-company');
    
    // Chat history array
    let messages = [];
    

    
    // Event listeners
    chatForm.addEventListener('submit', handleChatSubmit);
    chatInput.addEventListener('keydown', handleKeyDown);

    /**
     * Handles form submission when the user sends a message
     */
    function handleChatSubmit(e) {
        e.preventDefault();
        const query = chatInput.value.trim();
        if (query && !isLoading()) {
            sendMessage(query);
        }
    }
    
    /**
     * Handles sending a message when Enter key is pressed
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
        
        // Add avatar next to the message card
        const avatar = document.createElement('div');
        avatar.className = 'avatar-badge user-avatar-badge ms-2';
        avatar.textContent = 'You';
        wrapper.appendChild(avatar);
        chatHistory.appendChild(wrapper);
        scrollToBottom();
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
    function addAssistantMessage(content, citations) {
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
        // Handle citations
        let formattedContent = content || '';
        const messageId = 'msg-' + Date.now();
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
        const avatar = document.createElement('div');
        avatar.className = 'avatar-badge assistant-avatar-badge me-2';
        avatar.textContent = 'AI';
        wrapper.appendChild(avatar);
        wrapper.appendChild(card);
        chatHistory.appendChild(wrapper);
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
        errorMessage.textContent = text;
        errorContainer.classList.remove('d-none');
    }
    
    /**
     * Hides the error message
     */
    function hideError() {
        errorContainer.classList.add('d-none');
    }
    
    /**
     * Shows the loading indicator
     */
    function showLoading() {
        loadingIndicator.classList.remove('d-none');
        sendButton.disabled = true;
        if (typeof btnPersonalInfo !== 'undefined' && btnPersonalInfo) btnPersonalInfo.disabled = true;
        if (typeof btnWarranty !== 'undefined' && btnWarranty) btnWarranty.disabled = true;
        if (typeof btnCompany !== 'undefined' && btnCompany) btnCompany.disabled = true;
    }
    
    /**
     * Hides the loading indicator
     */
    function hideLoading() {
        loadingIndicator.classList.add('d-none');
        sendButton.disabled = false;
        if (typeof btnPersonalInfo !== 'undefined' && btnPersonalInfo) btnPersonalInfo.disabled = false;
        if (typeof btnWarranty !== 'undefined' && btnWarranty) btnWarranty.disabled = false;
        if (typeof btnCompany !== 'undefined' && btnCompany) btnCompany.disabled = false;
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
    function sendMessage(text) {
        hideError();
        
        // Add user message to UI
        addUserMessage(text);
        
        // Clear input field
        chatInput.value = '';
        
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
            
            // Extract citations from context
            const citations = message.context?.citations || [];
            
            // Add assistant message to UI
            addAssistantMessage(content, citations);
            
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
