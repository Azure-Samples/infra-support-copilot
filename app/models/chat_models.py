"""
Chat models for FastAPI RAG app
"""
from typing import List
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """
    Base chat message model representing a single message in the conversation
    
    Compatible with Azure OpenAI's message format, where:
    - role: can be 'system', 'user', or 'assistant'
    - content: contains the actual message text
    """
    role: str
    content: str


class ChatRequest(BaseModel):
    """Chat completion request model for the API endpoint"""
    messages: List[ChatMessage] = Field(..., description="List of chat messages")
