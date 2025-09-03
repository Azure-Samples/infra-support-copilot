"""
RAG Chat Service using Azure OpenAI and AI Search
"""
import logging
from typing import List, Tuple
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
from app.config import settings
from azure.search.documents import SearchClient

logger = logging.getLogger(__name__)


class RagChatService:
    """
    Service that provides RAG capabilities by connecting Azure OpenAI with Azure AI Search.
    """
    
    def __init__(self):
        # Store settings
        self.openai_endpoint = settings.azure_openai_endpoint
        self.gpt_deployment = settings.azure_openai_gpt_deployment
        self.search_url = settings.azure_search_service_url
        self.search_index_name_inventories = settings.azure_search_index_name_inventories
        self.search_index_name_incidents = settings.azure_search_index_name_incidents
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

        self.search_client_inventories = SearchClient(
            endpoint=self.search_url,
            index_name=self.search_index_name_inventories,
            credential=self.credential
        )

        self.search_client_incidents = SearchClient(
            endpoint=self.search_url,
            index_name=self.search_index_name_incidents,
            credential=self.credential
        )

    async def _select_indexes(self, condensed_query: str) -> Tuple[bool, bool]:
        """Use LLM to decide which indexes to search based on the condensed query."""
        import json
        index_selection_prompt = (
            "Decide which indexes should be searched to answer the user's request.\n"
            "Indexes: 'inventories' (ownership/contact/server metadata), 'incidents' (past incident info).\n"
            "Return ONLY JSON like {\"inventories\": true, \"incidents\": false}. If unsure, set a field to true.\n"
            f"Query: {condensed_query}"
        )
        try:
            selection_response = await self.openai_client.chat.completions.create(
                messages=[{"role": "user", "content": index_selection_prompt}],
                model=self.gpt_deployment
            )
            selection_text = selection_response.choices[0].message.content.strip()
            selection = json.loads(selection_text)
            return bool(selection.get("inventories", False)), bool(selection.get("incidents", False))
        except Exception as e:
            logger.warning(f"Index selection failed ({e}); defaulting to all indexes")
            return True, True

    async def get_chat_completion(self, effective_query: str, top_k: int = 3):
        """Multi-turn RAG flow considering recent chat history.
        Steps:
          1. Condense conversation into a standalone query.
          2. LLM-based index selection using condensed query.
          3. Retrieve documents from selected indexes with condensed query.
          4. Inject sources + original last user query into system prompt for final answer.
        """
        try:
            search_inventories, search_incidents = await self._select_indexes(effective_query)

            sources_parts: List[dict] = []

            def _accumulate(name: str, results):
                # Append each result as a separate citation element
                for doc in results:
                    content = doc.get("content", "")
                    if content:
                        sources_parts.append({
                            "title": name,
                            "content": content
                        })

            # Query inventories
            if search_inventories:
                try:
                    logger.debug("Querying inventories index")
                    inv_results = self.search_client_inventories.search(
                        search_text=effective_query,
                        top=1,
                        select="content"
                    )
                    _accumulate('Inventories', inv_results)
                except Exception as se:
                    logger.error(f"Search query failed for inventories index: {se}")
            # Query incidents
            if search_incidents:
                try:
                    logger.debug("Querying incidents index")
                    inc_results = self.search_client_incidents.search(
                        search_text=effective_query,
                        top=top_k,
                        select="content"
                    )
                    _accumulate('Incident', inc_results)
                except Exception as se:
                    logger.error(f"Search query failed for incidents index: {se}")

            return sources_parts
        except Exception as e:
            if hasattr(e, 'status_code'):
                logger.error(f"Error in get_chat_completion (status {getattr(e, 'status_code', 'n/a')}): {e}")
            else:
                logger.error(f"Error in get_chat_completion: {e}")
            raise

rag_chat_service = RagChatService()
