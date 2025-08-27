"""
RAG Chat Service using Azure OpenAI and AI Search
"""
import logging
from typing import List, Tuple
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
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

        logger.info("DecideTool initialized with environment variables")

    async def _condense_query(self, history: List[ChatMessage]) -> Tuple[str, str]:
        """Generate a standalone condensed query from recent multi-turn chat history.
        Returns (condensed_query, last_user_query)."""
        if not history:
            return "", ""

        recent_history = history[-20:] if len(history) > 20 else history
        # Extract last user query
        last_user_query = next((m.content for m in reversed(recent_history) if m.role == 'user'), recent_history[-1].content)

        # Build a lightweight transcript for rewriting (include roles)
        transcript_lines = []
        for m in recent_history:
            # Keep only user + assistant to limit tokens
            if m.role in ("user", "assistant"):
                transcript_lines.append(f"{m.role.upper()}: {m.content}")
        transcript = "\n".join(transcript_lines)[-5000:]  # crude length guard

        rewrite_prompt = (
            "You are a system that rewrites the latest user query into a standalone question. "
            "Incorporate necessary context from earlier turns (entities, references like 'that server', 'the previous incident'). "
            "Do NOT answer the question. Only output the rewritten query. If the last user query is already standalone, return it unchanged.\n\n"
            f"Conversation (most recent last):\n{transcript}\n\nRewritten standalone query:"
        )
        try:
            resp = await self.openai_client.chat.completions.create(
                model=self.gpt_deployment,
                messages=[{"role": "user", "content": rewrite_prompt}],
            )
            condensed = resp.choices[0].message.content.strip()
            logger.debug(f"Condensed query: {condensed}")
            # Basic sanity: avoid model giving multi-line answer instead of a query
            if '\n' in condensed and len(condensed.split('\n')) > 3:
                condensed = last_user_query  # fallback
        except Exception as e:
            logger.warning(f"Query condensation failed, falling back to last user query: {e}")
            condensed = last_user_query
        return condensed, last_user_query

    async def _select_tools(self, condensed_query: str) -> Tuple[bool, bool]:
        """Use LLM to decide which tools should be used based on the condensed query."""
        import json
        index_selection_prompt = (
            "Decide which tool should be searched to answer the user's request.\n"
            "Tools: 'RAG' (documents of ownership/contact/server metadata and incidents), 'SQL Query' (refer to the Azure Arc data to overview the whole service or numbers), 'Log Analytics' (query Azure Monitor logs).\n"
            "Return ONLY JSON like {\"rag\": true, \"sql_query\": false, \"log_analytics\": false}. If unsure, set a field to true.\n"
            f"Query: {condensed_query}"
        )
        try:
            selection_response = await self.openai_client.chat.completions.create(
                messages=[{"role": "user", "content": index_selection_prompt}],
                model=self.gpt_deployment
            )
            selection_text = selection_response.choices[0].message.content.strip()
            selection = json.loads(selection_text)
            return bool(selection.get("rag", False)), bool(selection.get("sql_query", False)), bool(selection.get("log_analytics", False))
        except Exception as e:
            logger.warning(f"Index selection failed ({e}); defaulting to all indexes")
            return True, True, True

    async def get_chat_completion(self, history: List[ChatMessage]):
        """Multi-turn RAG flow considering recent chat history.
        Steps:
          1. Condense conversation into a standalone query.
          2. LLM-based index selection using condensed query.
          3. Retrieve documents from selected indexes with condensed query.
          4. Inject sources + original last user query into system prompt for final answer.
        """
        try:
            condensed_query, last_user_query = await self._condense_query(history)
            effective_query = condensed_query or last_user_query

            search_rag, search_sql, search_log_analytics = await self._select_tools(effective_query)

            sources_parts: List[dict] = []

            def _accumulate(source: List[dict]):
                sources_parts.extend(source)

            # Query RAG
            if search_rag:
                try:
                    logger.debug("RAG")
                    response_rag = await rag_chat_service.get_chat_completion(effective_query)
                    _accumulate(response_rag)
                except Exception as se:
                    logger.error(f"Search query failed for RAG: {se}")
            # Query SQL database
            if search_sql:
                try:
                    logger.debug("Querying SQL database")
                    sql_results = await sql_query_service.get_chat_completion(effective_query)
                    _accumulate(sql_results)
                except Exception as se:
                    logger.error(f"Search query failed for SQL database: {se}")
            # Query Log Analytics
            if search_log_analytics:
                try:
                    logger.debug("Querying Log Analytics")
                    log_analytics_results = await log_analytics_service.get_chat_completion(effective_query)
                    _accumulate(log_analytics_results)
                except Exception as se:
                    logger.error(f"Search query failed for Log Analytics: {se}")

            # Combine sources into a single string for the system prompt
            sources = "\n\n".join(f"{src['title']}:\n{src['content']}" for src in sources_parts)

            # Final answer request
            final_content = self.system_prompt.format(
                query=last_user_query or effective_query,
                sources=sources
            )

            chat_resp = await self.openai_client.chat.completions.create(
                messages=[{"role": "user", "content": final_content}],
                model=self.gpt_deployment
            )

            # Extract assistant content from SDK object
            base_content = chat_resp.choices[0].message.content if chat_resp.choices and chat_resp.choices[0].message else ""

            # Build references section (1-based indexing for [docN])
            references_suffix = ""
            if sources_parts:
                refs = "".join(f"[doc{idx+1}]" for idx in range(len(sources_parts)))
                references_suffix = f"\n\nReferences: {refs}"

            # Build citations array expected by the frontend (title/filePath/url optional)
            citations = [{"title": s['title'], "content": s['content']} for s in sources_parts]

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
