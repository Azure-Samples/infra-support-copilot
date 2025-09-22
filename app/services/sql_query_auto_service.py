"""SQL Query Service
"""
import logging
import asyncio
import struct
from typing import List, Any, Dict

import pyodbc  # type: ignore
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

class SQLQueryService:
    """
    Service that provides SQL query capabilities
    """
    
    def __init__(self):
        # Store settings
        self.openai_endpoint = settings.azure_openai_endpoint
        self.gpt_deployment = settings.azure_openai_gpt_deployment
        self.embedding_deployment = settings.azure_openai_embedding_deployment
        self.search_url = settings.azure_search_service_url
        self.search_index_name_inventories = settings.azure_search_index_name_inventories
        self.search_index_name_incidents = settings.azure_search_index_name_incidents
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

        # Azure SQL settings
        self.sql_server = settings.azure_sql_server
        self.sql_database = settings.azure_sql_database
        self.use_aad = settings.use_aad
        self._sql_scope = "https://database.windows.net/.default"
        self._allowed_tables = {"virtual_machines", "network_interfaces", "installed_software"}
        self._default_row_limit = 50

        self.table_info = (
            "TABLE dbo.virtual_machines (\n"
            "    resource_id           NVARCHAR(512) NOT NULL PRIMARY KEY,\n"
            "    name                  NVARCHAR(128),\n"
            "    subscription_id       UNIQUEIDENTIFIER NULL,\n"
            "    resource_group        NVARCHAR(128),\n"
            "    location              NVARCHAR(64),\n"
            "    vm_size               NVARCHAR(64),\n"
            "    os_type               NVARCHAR(32),\n"
            "    os_name               NVARCHAR(128),\n"
            "    os_version            NVARCHAR(64),\n"
            "    provisioning_state    NVARCHAR(32),\n"
            "    priority              NVARCHAR(32),\n"
            "    time_created          DATETIME2,\n"
            "    power_state           NVARCHAR(64),\n"
            "    admin_username        NVARCHAR(64),\n"
            "    server_type_tag       NVARCHAR(128),\n"
            "    tags_json             NVARCHAR(MAX),\n"
            "    identity_principal_id UNIQUEIDENTIFIER NULL\n"
            ");\n\n"
            "TABLE dbo.network_interfaces (\n"
            "    resource_id        NVARCHAR(512) NOT NULL PRIMARY KEY,\n"
            "    name               NVARCHAR(128),\n"
            "    subscription_id    UNIQUEIDENTIFIER NULL,\n"
            "    resource_group     NVARCHAR(128),\n"
            "    location           NVARCHAR(64),\n"
            "    mac_address        NVARCHAR(32),\n"
            "    private_ip         NVARCHAR(64),\n"
            "    allocation_method  NVARCHAR(32),\n"
            "    accelerated        BIT,\n"
            "    primary_flag       BIT,\n"
            "    vm_resource_id     NVARCHAR(512) NULL REFERENCES dbo.virtual_machines(resource_id)\n"
            ");\n\n"
            "TABLE dbo.installed_software (\n"
            "    id              INT IDENTITY(1,1) PRIMARY KEY,\n"
            "    computer_name   NVARCHAR(256) NOT NULL,\n"
            "    software_name   NVARCHAR(512) NOT NULL,\n"
            "    current_version NVARCHAR(256),\n"
            "    publisher       NVARCHAR(512)\n"
            ");"
        )

    async def _generate_sql(self, user_query: str) -> str:
        """Generate a read-only SQL query."""
        prompt = (
            "You are an expert SQL query generator for Azure infrastructure data. Generate a read-only SQL query based on the user's requirements.\n\n"
            f"User Query: {user_query}\n"
            "INSTRUCTIONS:\n"
            "1. Analyze the user query to determine the logical order for the required columns in the SELECT clause\n"
            "2. Use LEFT OUTER JOIN to ensure all columns appear in results, even when related data doesn't exist\n"
            "3. Determine appropriate ORDER BY clause based on the user query context\n"
            "4. Use table aliases for readability (vm for virtual_machines, ni for network_interfaces, sw for installed_software)\n"
            "5. Only use SELECT statements - no INSERT, UPDATE, DELETE, DROP, etc.\n"
            "6. Join tables appropriately: vm.resource_id = ni.vm_resource_id for VM-NIC relationship\n"
            f"Available Tables and Schema:\n{self.table_info}\n\n"
            "EXAMPLE OUTPUT FORMATS:\n"
            "SELECT vm.resource_group, vm.name AS resource_name, ni.name AS network_interface_name\n"
            "FROM dbo.virtual_machines AS vm\n"
            "LEFT OUTER JOIN dbo.network_interfaces AS ni ON vm.resource_id = ni.vm_resource_id\n"
            "ORDER BY vm.resource_group, vm.name;\n\n"
            "Generate ONLY the SQL query without any explanation or markdown formatting:"
        )
        try:
            resp = await self.openai_client.chat.completions.create(
                model=self.gpt_deployment,
                messages=[{"role": "user", "content": prompt}]
            )
            sql = resp.choices[0].message.content.strip()
            # Strip code fences if any
            if sql.startswith("```"):
                sql = sql.strip("`\n")
                # remove possible language tag line
                if sql.lower().startswith("sql"):
                    sql = "\n".join(sql.splitlines()[1:])
            return sql
        except Exception as e:
            logger.error(f"Failed to generate SQL: {e}")
            # fallback simple query
            return f"SELECT TOP {self._default_row_limit} name, location, vm_size, power_state FROM dbo.virtual_machines ORDER BY name;"

    # --- SQL Execution helpers -------------------------------------------------
    def _build_connection(self) -> pyodbc.Connection:
        """Create a new ODBC connection (short-lived)."""
        server = self.sql_server.replace("tcp:", "")
        conn_str = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER=tcp:{server},1433;DATABASE={self.sql_database};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
        )
        if self.use_aad:
            token = self.credential.get_token(self._sql_scope)
            token_bytes = token.token.encode("utf-16-le")
            token_struct = struct.pack("=i", len(token_bytes)) + token_bytes
            attrs_before = {1256: token_struct}  # SQL_COPT_SS_ACCESS_TOKEN
            return pyodbc.connect(conn_str, attrs_before=attrs_before)
        raise RuntimeError("Azure SQL connection failed: AAD enabled but token acquisition failed or SQL Auth credentials missing")

    async def _execute_sql(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL synchronously in a thread and return list of dict rows."""
        def _work() -> List[Dict[str, Any]]:
            with self._build_connection() as conn:
                cur = conn.cursor()
                cur.execute(sql)
                cols = [c[0] for c in cur.description] if cur.description else []
                rows = cur.fetchall() if cols else []
                return [dict(zip(cols, r)) for r in rows]
        return await asyncio.to_thread(_work)

    # --- Safety / formatting ---------------------------------------------------
    def _is_safe_sql(self, sql: str) -> bool:
        lowered = sql.lower()
        forbidden = ["update", "delete", "insert", "merge", "drop", "alter", "truncate"]
        if any(f in lowered for f in forbidden):
            return False
        # ensure only allowed tables referenced (simple heuristic)
        for token in [" from ", " join "]:
            parts = lowered.split(token)
            if len(parts) > 1:
                # check following identifier
                for seg in parts[1:]:
                    ident = seg.strip().split()[0].strip('[];,')
                    if ident.startswith("dbo."):
                        ident = ident[4:]
                    if ident and ident not in self._allowed_tables:
                        return False
        return True

    def _rows_to_sources(self, rows: List[Dict[str, Any]], max_chars: int = 4000) -> str:
        if not rows:
            return "(no rows)"
        # simple tabular text (pipe separated)
        cols = list(rows[0].keys())
        lines = [" | ".join(cols)]
        for r in rows:
            lines.append(" | ".join(str(r.get(c, "")) for c in cols))
            if sum(len(line) for line in lines) > max_chars:
                lines.append("... (truncated) ...")
                break
        return "\n".join(lines)

    async def get_chat_completion(self, effective_query: str):
        """End-to-end chat completion with Azure SQL retrieval."""
        try:
            sql = await self._generate_sql(effective_query)
            if not self._is_safe_sql(sql):
                logger.warning(f"Unsafe SQL blocked: {sql}")
                sql = f"SELECT TOP {self._default_row_limit} name, location, vm_size, power_state FROM dbo.virtual_machines ORDER BY name;"  # safe fallback

            rows = await self._execute_sql(sql)
            sources = self._rows_to_sources(rows)

            return [{"title": "SQL Query", "content": f"SQL Query:\n{sql}\n\nResults:\n{sources}"}]
        except Exception as e:
            logger.error(f"Error in get_chat_completion: {e}")
            raise

sql_query_auto_service = SQLQueryService()
