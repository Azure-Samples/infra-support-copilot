"""
RAG Chat Service using Azure OpenAI and AI Search
"""
import logging
import json
import uuid
import asyncio
from typing import List
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI, RateLimitError
from app.models.chat_models import ChatMessage
from app.config import settings
from app.services.rag_chat_service import rag_chat_service
from app.services.sql_query_service import sql_query_service
from app.services.log_analytics_service import log_analytics_service

logger = logging.getLogger(__name__)


class DecideTool:
    """
    Decide which tool to use for a given task.
    """
    
    def __init__(self):
        # Store settings
        self.openai_endpoint = settings.azure_openai_endpoint
        self.gpt_deployment = settings.azure_openai_gpt_deployment
        self.system_prompt = settings.system_prompt
        self.azure_openai_api_version = settings.azure_openai_api_version

        # Create Azure credentials for managed identity
        # This allows secure, passwordless authentication to Azure services
        self.credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            self.credential,
            "https://cognitiveservices.azure.com/.default"
        )
        
        # Create Azure OpenAI client
        # We use the latest Azure OpenAI Python SDK with async support
        # NOTE: api_version must be a valid Azure OpenAI REST API version, not a model version.
        # If you specify a future / invalid version you may receive 403/404 errors.
        # Adjust here if your resource supports a newer version.
        self.openai_client = AsyncAzureOpenAI(
            azure_endpoint=self.openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=self.azure_openai_api_version
        )

    def emit(self, event: str, payload: dict):
        logger.info(json.dumps({"event": event, **payload}, ensure_ascii=False))

    def _truncate_text(self, text: str, max_chars: int = 20000) -> str:
        """Trim text to a safe character budget to avoid excessive token usage.
        Roughly ~4 chars per token ⇒ 20k chars ≈ 5k tokens.
        """
        if not text:
            return text
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n... (truncated)"

    def _trim_history_for_prompt(self, history: List[ChatMessage], keep_last: int = 6) -> List[ChatMessage]:
        """Keep only the most recent messages to control prompt size."""
        try:
            return history[-keep_last:]
        except Exception:
            return history

    async def _retry_openai_call(self, func, max_retries=3, base_delay=1.5):
        """Retry OpenAI API calls with exponential backoff for rate limits."""
        for attempt in range(max_retries):
            try:
                return await func()
            except RateLimitError as e:
                if attempt == max_retries - 1:
                    logger.error(f"Rate limit exceeded after {max_retries} attempts: {e}")
                    raise
                
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Rate limit hit (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {e}")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"OpenAI API call failed: {e}")
                raise

    async def get_chat_completion(self, history: List[ChatMessage], conversation_id: str = "") -> dict:
        """Multi-turn RAG flow considering recent chat history.
        Steps:
          1. Condense conversation into a standalone query.
          2. LLM-based index selection using condensed query.
          3. Retrieve documents from selected indexes with condensed query.
          4. Inject sources + original last user query into system prompt for final answer.
        """
        try:
            new_conversation_id = str(uuid.uuid4())

            if history[-1].content.startswith(";;SQL;;"):
                sql_results = await sql_query_service.get_chat_completion(history[-1].content)
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": f"{sql_results[0]['content']}",
                                "context": {"citations": []},
                                "metadata": {"conversation_id": conversation_id}
                            }
                        }
                    ]
                }
            
            if history[-1].content.startswith(";;EXECUTE;;"):
                sql_results = await sql_query_service.get_chat_completion(f"{history[-1].content}|||{history[-5].content}")
                citations = [{"title": sql_results[0]['title'], "content": sql_results[0]['content']}]
                sources = "\n\n".join(f"{src['title']}:\n{src['content']}" for src in citations)

                # Final answer request
                final_content = self.system_prompt.format(
                    query=history[-5].content,
                    sources=sources
                )

                chat_resp = await self._retry_openai_call(
                    lambda: self.openai_client.chat.completions.create(
                        messages=[{"role": "user", "content": final_content}],
                        model=self.gpt_deployment
                    )
                )

                # Extract assistant content from SDK object
                base_content = chat_resp.choices[0].message.content if chat_resp.choices and chat_resp.choices[0].message else ""

                self.emit("chat_prompt", {
                    "conversation_id": conversation_id,
                    "turn_id": str(uuid.uuid4()),
                    "user_id": 'assistant',
                    "prompt": base_content,
                    "prompt_chars": len(base_content),
                    "metadata": {},
                })


                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": f"{base_content}\nReferences: [doc1]",
                                "context": {"citations": citations}
                            }
                        }
                    ]
                }
        
            self.emit("chat_prompt", {
                "conversation_id": new_conversation_id,
                "turn_id": str(uuid.uuid4()),
                "user_id": 'user',
                "prompt": history[-1].content,
                "prompt_chars": len(history[-1].content),
                "metadata": {},
            })

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "rag_chat_service.get_chat_completion",
                        "description": "Search RAG index for relevant documents (inventories, ownership, contacts, incidents).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query."
                                }
                            },
                            "required": ["query"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "sql_query_service.get_chat_completion",
                        "description": "Query SQL database to get statistical information (servers, virtual machines, installed softwares).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query."
                                }
                            },
                            "required": ["query"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "log_analytics_service.get_chat_completion",
                        "description": "Query Log Analytics to get log information (AppServiceAuditLogs, AppServiceConsoleLogs, AppServiceHttpLogs, AppServicePlatformLogs, AzureDiagnostics, AzureMetrics, Usage).",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query."
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }
            ]

            sources_parts: List[dict] = []

            trimmed_history = self._trim_history_for_prompt(history)
            messages = trimmed_history[:-1] + [{"role": "system", "content": "Select the single best tool."}]
            messages.append({"role": "user", "content": trimmed_history[-1].content})

            chat_resp = await self._retry_openai_call(
                lambda: self.openai_client.chat.completions.create(
                    messages=messages,
                    model=self.gpt_deployment,
                    tools=tools,
                    tool_choice="auto",
                )
            )
            
            def _accumulate(source: List[dict]):
                sources_parts.extend(source)

            msg = chat_resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                for tc in tool_calls:
                    fname = tc.function.name
                    fargs = json.loads(tc.function.arguments or "{}")
                    q = fargs.get("query", history[-1].content)

                    if fname == "sql_query_service.get_chat_completion":
                        try:
                            sql_results = await sql_query_service.get_chat_completion(q)
                            return {
                                "choices": [
                                    {
                                        "message": {
                                            "role": "assistant",
                                            "content": f"{sql_results[0]['content']}",
                                            "context": {"citations": []},
                                            "metadata": {"conversation_id": new_conversation_id}
                                        }
                                    }
                                ]
                            }
                        except Exception as se:
                            logger.error(f"Search query failed for SQL database: {se}")

                    elif fname == "rag_chat_service.get_chat_completion":
                        try:
                            response_rag = await rag_chat_service.get_chat_completion(q)
                            _accumulate(response_rag)
                        except Exception as se:
                            logger.error(f"Search query failed for RAG: {se}")

                    elif fname == "log_analytics_service.get_chat_completion":
                        try:
                            response_logs = await log_analytics_service.get_chat_completion(q)
                            _accumulate(response_logs)
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")

            # Final answer request
            # Combine sources into a single string for the system prompt (after tool execution)
            sources_joined = "\n\n".join(f"{src['title']}:\n{src['content']}" for src in sources_parts)
            sources = self._truncate_text(sources_joined)

            final_content = self.system_prompt.format(
                query=history[-1].content,
                sources=sources
            )

            trimmed_history = self._trim_history_for_prompt(history)
            final_messages = trimmed_history[:-1] + [{"role": "user", "content": final_content}]

            final_response = await self._retry_openai_call(
                lambda: self.openai_client.chat.completions.create(
                    messages=final_messages,
                    model=self.gpt_deployment,
                )
            )

            # Extract assistant content from SDK object
            base_content = final_response.choices[0].message.content if final_response.choices and final_response.choices[0].message else ""

            # Build references section (1-based indexing for [docN])
            references_suffix = ""
            if sources_parts:
                refs = "".join(f"[doc{idx+1}]" for idx in range(len(sources_parts)))
                references_suffix = f"\n\nReferences: {refs}"

            # Build citations array expected by the frontend (title/filePath/url optional)
            citations = [{"title": s['title'], "content": s['content']} for s in sources_parts]

            self.emit("chat_prompt", {
                "conversation_id": new_conversation_id,
                "turn_id": str(uuid.uuid4()),
                "user_id": 'assistant',
                "prompt": base_content,
                "prompt_chars": len(base_content),
                "metadata": {},
            })

            # Return a plain JSON-serializable structure used by the UI
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"{base_content}{references_suffix}",
                            "context": {"citations": citations}
                        }
                    }
                ]
            }
        except Exception as e:
            if hasattr(e, 'status_code'):
                logger.error(f"Error in get_chat_completion (status {getattr(e, 'status_code', 'n/a')}): {e}")
            else:
                logger.error(f"Error in get_chat_completion: {e}")
            raise

decide_tool = DecideTool()
