"""
Config settings for the FastAPI RAG app
"""
from typing import Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

logger = logging.getLogger(__name__)


class OpenAISettings(BaseModel):
    """Azure OpenAI settings"""
    endpoint: str
    gpt_deployment: str
    embedding_deployment: Optional[str] = ""


class SearchSettings(BaseModel):
    """Azure AI Search settings"""
    url: str
    index_name: str


class AppSettings(BaseSettings):
    """Application settings with environment variable loading capabilities"""
    azure_subscription_id: str = Field("", validation_alias="AZURE_SUBSCRIPTION_ID")
    azure_env_name: str = Field("", validation_alias="AZURE_ENV_NAME")
    azure_storage_account_name: str = Field("", validation_alias="AZURE_STORAGE_ACCOUNT_NAME")
    azure_search_service_name: str = Field("", validation_alias="AZURE_SEARCH_SERVICE_NAME")
    azure_app_service_name: str = Field("", validation_alias="AZURE_APP_SERVICE_NAME")
    azure_resource_group: str = Field("", validation_alias="AZURE_RESOURCE_GROUP")  # optional, supplied by azd
    
    # Azure OpenAI Settings
    azure_openai_endpoint: str = Field(..., validation_alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_gpt_deployment: str = Field(..., validation_alias="AZURE_OPENAI_GPT_DEPLOYMENT")
    azure_openai_embedding_deployment: str = Field("", validation_alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    azure_openai_api_version: str = Field(..., validation_alias="AZURE_OPENAI_API_VERSION")
    
    # Azure AI Search Settings
    azure_search_service_url: str = Field(..., validation_alias="AZURE_SEARCH_SERVICE_URL")
    azure_search_index_name_inventories: str = Field(..., validation_alias="AZURE_SEARCH_INDEX_NAME_INVENTORIES")
    azure_search_index_name_incidents: str = Field(..., validation_alias="AZURE_SEARCH_INDEX_NAME_INCIDENTS")

    # SQL Database Settings
    azure_sql_server: str = Field(..., validation_alias="AZURE_SQL_SERVER")
    azure_sql_database: str = Field("arclog", validation_alias="AZURE_SQL_DATABASE_NAME")
    use_aad: bool = Field(..., validation_alias="USE_AAD")

    # Other
    client_public_ip: Optional[str] = Field(None, validation_alias="CLIENT_PUBLIC_IP")

    # Other settings
    system_prompt: str = Field(
        "You are an infrastructure knowledge assistant answering about servers, incidents and ownership.\nUse ONLY the information contained in the Sources section. If information is missing, state you don't know. Never invent data.\n\nTOLERATE TYPOS & NORMALIZE:\n- Accept minor typos / case differences / missing leading zeros in server IDs (e.g. srv1, SRV1, SRV01 => SRV001 if that exists; payment-gw-stagin => payment-gw-staging).\n- Normalize server_id pattern: PREFIX + digits. If digits length < canonical (3), zero‑pad (SRV1 => SRV001). Remove extra zeros when comparing.\n- Ignore hyphens/underscores/case when matching IDs or team names (auth_api_prod ~ auth-api-prod).\n- For team / owner names allow edit distance 1 (Platfrom => Platform).\n- If multiple candidates remain, list the possible matches and ask the user to clarify; do not guess.\n\nANSWER FORMAT:\n- Provide concise bullet points (<=5) unless user requests another format.\n- For each factual bullet cite the server_id or incident identifier in parentheses.\n- If summarizing multiple rows, group by environment or status.\n\nRULES:\n1. Use only facts from Sources.\n2. Do not output internal reasoning.\n3. Clearly say 'insufficient information' when data not found.\n4. Do not include unrelated marketing or speculative content.\n\nNow answer the user Query in the language of the user Query using only Sources.\nQuery: {query}\nSources:\n{sources}",
    validation_alias="SYSTEM_PROMPT"
    )
    
    # Optional port setting
    port: int = Field(8080, validation_alias="PORT")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )
    
    @property
    def openai(self) -> OpenAISettings:
        """Return OpenAI settings in the format used by the application"""
        return OpenAISettings(
            endpoint=self.azure_openai_endpoint,
            gpt_deployment=self.azure_openai_gpt_deployment,
            embedding_deployment=self.azure_openai_embedding_deployment
        )
    
    @property
    def search_inventories(self) -> SearchSettings:
        """Primary Search settings (inventories index)"""
        return SearchSettings(
            url=self.azure_search_service_url,
            index_name=self.azure_search_index_name_inventories
        )

    def search_incidents(self) -> SearchSettings:
        """Secondary Search settings (incidents index)"""
        return SearchSettings(
            url=self.azure_search_service_url,
            index_name=self.azure_search_index_name_incidents
        )

settings: AppSettings = AppSettings(
    azure_subscription_id="",
    azure_env_name="",
    azure_storage_account_name="",
    azure_search_service_name="",
    azure_app_service_name="",
    azure_resource_group="",
    azure_openai_endpoint="",
    azure_openai_gpt_deployment="",
    azure_openai_embedding_deployment="",
    azure_openai_api_version="",
    azure_search_service_url="",
    azure_search_index_name_inventories="",
    azure_search_index_name_incidents="",
    azure_sql_server="",
    azure_sql_database="arclog",
    use_aad=False,
    client_public_ip=None,
    system_prompt="You are an infrastructure knowledge assistant answering about servers, incidents and ownership.\nUse ONLY the information contained in the Sources section. If information is missing, state you don't know. Never invent data.\n\nTOLERATE TYPOS & NORMALIZE:\n- Accept minor typos / case differences / missing leading zeros in server IDs (e.g. srv1, SRV1, SRV01 => SRV001 if that exists; payment-gw-stagin => payment-gw-staging).\n- Normalize server_id pattern: PREFIX + digits. If digits length < canonical (3), zero‑pad (SRV1 => SRV001). Remove extra zeros when comparing.\n- Ignore hyphens/underscores/case when matching IDs or team names (auth_api_prod ~ auth-api-prod).\n- For team / owner names allow edit distance 1 (Platfrom => Platform).\n- If multiple candidates remain, list the possible matches and ask the user to clarify; do not guess.\n\nANSWER FORMAT:\n- Provide concise bullet points (<=5) unless user requests another format.\n- For each factual bullet cite the server_id or incident identifier in parentheses.\n- If summarizing multiple rows, group by environment or status.\n\nRULES:\n1. Use only facts from Sources.\n2. Do not output internal reasoning.\n3. Clearly say 'insufficient information' when data not found.\n4. Do not include unrelated marketing or speculative content.\n\nNow answer the user Query in the language of the user Query using only Sources.\nQuery: {query}\nSources:\n{sources}",
    port=8080
)
