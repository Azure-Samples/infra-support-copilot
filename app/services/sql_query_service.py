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
            "    resource_id           NVARCHAR(512) NOT NULL PRIMARY KEY, # virtual machine identifier\n"
            "    name                  NVARCHAR(128), # virtual machine name\n"
            "    subscription_id       UNIQUEIDENTIFIER NULL, # subscription identifier\n"
            "    resource_group        NVARCHAR(128), # resource group name\n"
            "    location              NVARCHAR(64), # Azure region\n"
            "    vm_size               NVARCHAR(64), # VM size\n"
            "    os_type               NVARCHAR(32), # OS type\n"
            "    os_name               NVARCHAR(128), # OS name\n"
            "    os_version            NVARCHAR(64), # OS version\n"
            "    provisioning_state    NVARCHAR(32), # Provisioning state\n"
            "    priority              NVARCHAR(32), # Priority\n"
            "    time_created          DATETIME2, # Time created\n"
            "    power_state           NVARCHAR(64), # Power state\n"
            "    admin_username        NVARCHAR(64), # Admin username\n"
            "    server_type_tag       NVARCHAR(128), # Server type tag\n"
            "    tags_json             NVARCHAR(MAX), # Tags JSON\n"
            "    identity_principal_id UNIQUEIDENTIFIER NULL # Identity principal ID\n"
            ");\n\n"
            "TABLE dbo.network_interfaces (\n"
            "    resource_id        NVARCHAR(512) NOT NULL PRIMARY KEY, # Network interface identifier\n"
            "    name               NVARCHAR(128), # Network interface name\n"
            "    subscription_id    UNIQUEIDENTIFIER NULL, # Subscription identifier\n"
            "    resource_group     NVARCHAR(128), # Resource group name\n"
            "    location           NVARCHAR(64), # Azure region\n"
            "    mac_address        NVARCHAR(32), # MAC address\n"
            "    private_ip         NVARCHAR(64), # Private IP address\n"
            "    allocation_method  NVARCHAR(32), # Allocation method\n"
            "    accelerated        BIT, # Accelerated networking\n"
            "    primary_flag       BIT, # Primary network interface flag\n"
            "    vm_resource_id     NVARCHAR(512) NULL REFERENCES dbo.virtual_machines(resource_id) # Virtual machine identifier\n"
            ");\n\n"
            "TABLE dbo.installed_software (\n"
            "    id              INT IDENTITY(1,1) PRIMARY KEY, # Software installation identifier\n"
            "    computer_name   NVARCHAR(256) NOT NULL, # Name of the computer\n"
            "    software_name   NVARCHAR(512) NOT NULL, # Name of the installed software\n"
            "    current_version NVARCHAR(256), # Current version of the software\n"
            "    publisher       NVARCHAR(512) # Publisher of the software\n"
            ");"
        )

    async def _generate_sql(self, wanted_columns: List[str], user_query: str) -> str:
        """Generate a read-only SQL query."""
        prompt = (
            "You are an expert SQL query generator for Azure infrastructure data. Generate a read-only SQL query based on the user's requirements.\n\n"
            f"User Query: {user_query}\n"
            f"Required Columns: {', '.join(wanted_columns)}\n\n"
            "INSTRUCTIONS:\n"
            "1. Analyze the user query to determine the logical order for the required columns in the SELECT clause\n"
            "2. Use LEFT OUTER JOIN to ensure all columns appear in results, even when related data doesn't exist\n"
            "3. Determine appropriate ORDER BY clause based on the user query context\n"
            "4. Use table aliases for readability (vm for virtual_machines, ni for network_interfaces, sw for installed_software)\n"
            "5. Only use SELECT statements - no INSERT, UPDATE, DELETE, DROP, etc.\n"
            "6. Join tables appropriately: vm.resource_id = ni.vm_resource_id for VM-NIC relationship\n"
            f"Available Tables and Schema:\n{self.table_info}\n\n"
            "EXAMPLE OUTPUT FORMATS:\n"
            "Basic join:\n"
            "SELECT vm.resource_group, vm.name AS resource_name, ni.name AS network_interface_name\n"
            "FROM dbo.virtual_machines AS vm\n"
            "LEFT OUTER JOIN dbo.network_interfaces AS ni ON vm.resource_id = ni.vm_resource_id\n"
            "ORDER BY vm.resource_group, vm.name;\n\n"
            "Generate ONLY the SQL query without any explanation or markdown formatting:"
        )
        
        resp_sql = await self.openai_client.chat.completions.create(
            model=self.gpt_deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        return resp_sql.choices[0].message.content.strip()
        

    # --- SQL Execution helpers -------------------------------------------------
    def _build_connection(self) -> pyodbc.Connection:
        """Create a new ODBC connection (short-lived)."""
        server = self.sql_server.replace("tcp:", "")
        conn_str = (
            "DRIVER={ODBC Driver 18 for SQL Server};"
            f"SERVER=tcp:{server},1433;DATABASE={self.sql_database};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;Authentication=ActiveDirectoryAccessToken;"
        )
        
        try:
            if self.use_aad:
                logger.info(f"Attempting AAD authentication to SQL server: {server}")
                logger.info(f"Database: {self.sql_database}")
                logger.info(f"Connection string: {conn_str}")
                
                try:
                    token = self.credential.get_token(self._sql_scope)
                    logger.info(f"Successfully acquired AAD token. Token expires at: {token.expires_on}")
                    
                    token_bytes = token.token.encode("utf-16-le")
                    token_struct = struct.pack("=i", len(token_bytes)) + token_bytes
                    attrs_before = {1256: token_struct}  # SQL_COPT_SS_ACCESS_TOKEN
                    
                    logger.info("Attempting to connect with AAD token...")
                    connection = pyodbc.connect(conn_str, attrs_before=attrs_before)
                    logger.info("Successfully connected to SQL database with AAD authentication")
                    return connection
                    
                except Exception as token_error:
                    logger.error(f"Failed to acquire AAD token: {type(token_error).__name__}: {str(token_error)}")
                    raise RuntimeError(f"AAD token acquisition failed: {type(token_error).__name__}: {str(token_error)}")
            else:
                raise RuntimeError("SQL authentication is disabled. USE_AAD is False but no SQL credentials are configured.")
                
        except pyodbc.Error as db_error:
            logger.error(f"Database connection error: {type(db_error).__name__}: {str(db_error)}")
            logger.error(f"Error details - Server: {server}, Database: {self.sql_database}")
            logger.error(f"AAD enabled: {self.use_aad}")
            raise RuntimeError(f"SQL Database connection failed: {type(db_error).__name__}: {str(db_error)}. Server: {server}, Database: {self.sql_database}, AAD: {self.use_aad}")
        except Exception as general_error:
            logger.error(f"Unexpected connection error: {type(general_error).__name__}: {str(general_error)}")
            raise RuntimeError(f"Unexpected SQL connection error: {type(general_error).__name__}: {str(general_error)}. Server: {server}, Database: {self.sql_database}")

    async def _execute_sql(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL synchronously in a thread and return list of dict rows."""
        def _work() -> List[Dict[str, Any]]:
            try:
                logger.info(f"Executing SQL query: {sql}")
                with self._build_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(sql)
                    cols = [c[0] for c in cur.description] if cur.description else []
                    rows = cur.fetchall() if cols else []
                    result = [dict(zip(cols, r)) for r in rows]
                    logger.info(f"SQL query executed successfully, returned {len(result)} rows")
                    return result
            except Exception as e:
                logger.error(f"SQL execution failed: {type(e).__name__}: {str(e)}")
                logger.error(f"Failed query: {sql}")
                raise RuntimeError(f"SQL execution error: {type(e).__name__}: {str(e)}. Query: {sql}")
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
        # simple tabular text (pipe separated, markdown table)
        cols = list(rows[0].keys())
        header = " | ".join(cols)
        separator = " | ".join(["---"] * len(cols))
        lines = [header, separator]
        for r in rows:
            lines.append(" | ".join(str(r.get(c, "")) for c in cols))
        return "\n".join(lines)

    async def get_chat_completion(self, effective_query: str):
        """End-to-end chat completion with Azure SQL retrieval."""
        try:
            logger.info(f"Processing query: {effective_query}")
            
            if effective_query.upper().startswith(";;SQL;;"):     
                sql_part = effective_query.split(";;SQL;;", 1)[1]
                items = sql_part.split(',')
                quoted_items = [f"'{item[4:].strip()}'" for item in items]
                sql = f"""
                    SELECT TABLE_NAME, COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME IN ({','.join(quoted_items)})
                    ORDER BY TABLE_NAME, ORDINAL_POSITION;
                """
                logger.info(f"Executing SQL for columns: {sql}")
                rows = await self._execute_sql(sql)
                columns = self._rows_to_sources(rows)
                return [{"title": "COLUMNS", "content": f";;COLUMNS;;{columns}"}]
            elif effective_query.upper().startswith(";;EXECUTE;;"):
                [wanted_columns, user_query] = effective_query.split("|||")
                sql = await self._generate_sql(wanted_columns, user_query)
                if not self._is_safe_sql(sql):
                    logger.warning(f"Unsafe SQL blocked: {sql}")
                    sql = f"SELECT TOP {self._default_row_limit} name, location, vm_size, power_state FROM dbo.virtual_machines ORDER BY name;"  # safe fallback

                rows = await self._execute_sql(sql)

                sources = self._rows_to_sources(rows)

                return [{"title": "SQL Query", "content": f"## SQL Query:\n{sql}\n\n## Results:\n{sources}"}]
            else:
                return [{'title': 'SELECTABLE', 'content': f';;SELECTABLE;;{",".join("dbo." + table for table in self._allowed_tables)}'}]
        except Exception as e:
            logger.error(f"Error in get_chat_completion: {type(e).__name__}: {str(e)}")
            logger.error(f"Query that failed: {effective_query}")
            logger.error(f"SQL Server: {self.sql_server}")
            logger.error(f"SQL Database: {self.sql_database}")
            logger.error(f"AAD enabled: {self.use_aad}")
            
            # Create detailed error message
            error_details = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "query": effective_query,
                "sql_server": self.sql_server,
                "sql_database": self.sql_database,
                "aad_enabled": self.use_aad,
                "openai_endpoint": self.openai_endpoint,
                "gpt_deployment": self.gpt_deployment
            }
            
            detailed_error = f"SQL Service Error Details:\n" + "\n".join([f"- {k}: {v}" for k, v in error_details.items()])
            raise RuntimeError(detailed_error)

sql_query_service = SQLQueryService()
