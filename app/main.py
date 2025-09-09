"""
FastAPI RAG app using Azure OpenAI and Azure AI Search
"""
import os
import logging
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from opencensus.ext.azure.log_exporter import AzureLogHandler
from opencensus.trace import config_integration

from app.models.chat_models import ChatRequest
from app.services.decide_tool import decide_tool

load_dotenv()

# Application Insightsの設定
# connection_string = os.getenv('APPLICATIONINSIGHTS_CONNECTION_STRING')
# if connection_string:
#     azure_log_handler = AzureLogHandler(connection_string=connection_string)
#     azure_log_handler.setLevel(logging.INFO)

#     root_logger = logging.getLogger()
#     root_logger.addHandler(azure_log_handler)
#     root_logger.setLevel(logging.INFO)

#     config_integration.trace_integrations(['requests', 'httplib'])

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)

# if connection_string:
#     logging.getLogger().addHandler(azure_log_handler)


logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="FastAPI RAG with Azure OpenAI and Azure AI Search",
    description="A FastAPI application that demonstrates retrieval augmented generation using Azure OpenAI and Azure AI Search.",
    version="1.0.0",
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up template directory
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request):
    """
    Serve the main chat interface
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/chat/completion")
async def chat_completion(chat_request: ChatRequest):
    """
    Process a chat completion request with RAG capabilities
    
    This endpoint:
    1. Receives the chat history from the client
    2. Passes it to the RAG service for processing
    3. Returns AI-generated responses with citations
    4. Handles errors gracefully with user-friendly messages
    """
    try:
        if not chat_request.messages:
            raise HTTPException(status_code=400, detail="Messages cannot be empty")
        
        # Get chat completion from RAG service
        response = await decide_tool.get_chat_completion(chat_request.messages, chat_request.conversation_id)
        
        return response
        
    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"Error in chat completion: {str(e)}")
        
        # Handle specific error types with friendly messages
        if "rate limit" in error_str or "capacity" in error_str or "quota" in error_str:
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "The AI service is currently experiencing high demand. Please wait a moment and try again."
                    }
                }]
            }
        else:
            # Return a standard error response for all other errors
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": f"An error occurred: {str(e)}"
                    }
                }]
            }


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "ok"}


if __name__ == "__main__":
    # This lets you test the application locally with Uvicorn
    # For production deployment, use a proper ASGI server like Gunicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
