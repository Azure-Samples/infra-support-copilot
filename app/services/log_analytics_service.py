from __future__ import annotations

import logging
from typing import Any, Dict, List

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.monitor.query import LogsQueryClient
from azure.monitor.query import LogsQueryStatus
from openai import AsyncAzureOpenAI
from app.config import settings
from datetime import timedelta

logger = logging.getLogger(__name__)

class LogAnalyticsService:
    """
    Lightweight client for querying Azure Monitor Log Analytics.

    Contract:
    - Inputs: workspace_id (GUID), kusto query string, timespan in ISO8601 (e.g., 'PT1H') or timedelta
    - Output: list of rows as dicts or empty list; raises RuntimeError on API failures
    - Auth: DefaultAzureCredential (managed identity on App Service or local dev)
    """

    def __init__(self):
        self.azure_log_analytics_customer_id = settings.azure_log_analytics_customer_id
        self.openai_endpoint = settings.azure_openai_endpoint
        self.azure_openai_api_version = settings.azure_openai_api_version
        self.gpt_deployment = settings.azure_openai_gpt_deployment

        self.credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            self.credential,
            "https://cognitiveservices.azure.com/.default"
        )

        self.openai_client = AsyncAzureOpenAI(
            azure_endpoint=self.openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=self.azure_openai_api_version
        )

        self.log_query_client = LogsQueryClient(credential=self.credential)

    def query(self, kusto: str) -> List[Dict[str, Any]]:
        """Execute a Kusto query against the workspace and return rows as list[dict]."""
        if not kusto or not kusto.strip():
            return []

        response = self.log_query_client.query_workspace(
            workspace_id=self.azure_log_analytics_customer_id,
            query=kusto,
            timespan=timedelta(days=1),
        )

        if response.status != LogsQueryStatus.SUCCESS:
            raise RuntimeError(f"Log query failed: status={response.status} partial={getattr(response, 'partial_error', None)}")

        tables = response.tables or []
        if not tables:
            return []

        table = tables[0]

        columns = table.columns
        rows: List[Dict[str, Any]] = []
        for r in table.rows:
            rows.append({col: val for col, val in zip(columns, r)})
        return rows
    
    def rows_to_markdown_table(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "(no rows)"
        # Limits to keep token usage under control
        max_cols = 12
        max_rows = 50
        max_cell_chars = 200

        cols_all = list(rows[0].keys())
        cols = cols_all[:max_cols]
        header = " | ".join(cols)
        separator = " | ".join(["---"] * len(cols))
        lines = [header, separator]

        row_count = 0
        for r in rows:
            if row_count >= max_rows:
                break
            trimmed = []
            for c in cols:
                val = str(r.get(c, ""))
                if len(val) > max_cell_chars:
                    val = val[:max_cell_chars] + "…"
                trimmed.append(val)
            lines.append(" | ".join(trimmed))
            row_count += 1

        truncated_notice_parts = []
        if len(cols_all) > max_cols:
            truncated_notice_parts.append(f"columns {len(cols_all) - max_cols} more hidden")
        if len(rows) > max_rows:
            truncated_notice_parts.append(f"rows {len(rows) - max_rows} more hidden")
        if truncated_notice_parts:
            lines.append("")
            lines.append(f"(truncated: {'; '.join(truncated_notice_parts)})")
        return "\n".join(lines)
    
    async def get_chat_completion(self, effective_query: str):
        try:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_appservice_audit_logs_errors",
                        "description": "Search Log Analytics (AppServiceAuditLogs: Logs generated when publishing users successfully log on via one of the App Service publishing protocols.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_appservice_console_logs_errors",
                        "description": "Search Log Analytics (AppServiceConsoleLogs: Console logs generated from application or container.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_appservice_http_logs_errors",
                        "description": "Search Log Analytics (AppServiceHttpLogs: Incoming HTTP requests on App Service. Use these logs to monitor application health, performance and usage patterns.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_appservice_platform_logs_errors",
                        "description": "Search Log Analytics (AppServicePlatformLogs: Logs generated through AppService platform for your application.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_azure_diagnostics_cognitive_services",
                        "description": "Search Log Analytics for Azure OpenAI (AzureDiagnostics: Diagnostic logs emitted by Azure services describe the operation of those services or resources. All diagnostic logs share a common top-level schema, which services extend to emit unique properties for their specifc events.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_azure_diagnostics_ai_search",
                        "description": "Search Log Analytics for Azure AI Search (AzureDiagnostics: Diagnostic logs emitted by Azure services describe the operation of those services or resources. All diagnostic logs share a common top-level schema, which services extend to emit unique properties for their specifc events.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_azure_diagnostics_sql",
                        "description": "Search Log Analytics for SQL (AzureDiagnostics: Diagnostic logs emitted by Azure services describe the operation of those services or resources. All diagnostic logs share a common top-level schema, which services extend to emit unique properties for their specifc events.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_azure_metrics",
                        "description": "Search Log Analytics (AzureMetrics: Metric data emitted by Azure services that measure their health and performance.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "self.query_useage",
                        "description": "Search Log Analytics (Usage: Hourly usage data for each table in the workspace.).",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
            ]

            sources = []

            chat_resp = await self.openai_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Select the single best tool."},
                    {"role": "user", "content": effective_query}
                ],
                model=self.gpt_deployment,
                tools=tools,
                tool_choice="auto"
            )

            msg = chat_resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                for tc in tool_calls:
                    fname = tc.function.name

                    if fname == "self.query_appservice_audit_logs_errors":
                        try:
                            sql_results = self.query_appservice_audit_logs_errors()
                            sources.append({"title": "Log Analytics (AppServiceAuditLogs)", "content": f"## Errors:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")

                    elif fname == "self.query_appservice_console_logs_errors":
                        try:
                            sql_results = self.query_appservice_console_logs_errors()
                            sources.append({"title": "Log Analytics (AppServiceConsoleLogs)", "content": f"## Errors:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")

                    elif fname == "self.query_appservice_http_logs_errors":
                        try:
                            sql_results = self.query_appservice_http_logs_errors()
                            sources.append({"title": "Log Analytics (AppServiceHttpLogs)", "content": f"## Errors:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
                    elif fname == "self.query_appservice_platform_logs_errors":
                        try:
                            sql_results = self.query_appservice_platform_logs_errors()
                            sources.append({"title": "Log Analytics (AppServicePlatformLogs)", "content": f"## Errors:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
                    elif fname == "self.query_azure_diagnostics_cognitive_services":
                        try:
                            sql_results = self.query_azure_diagnostics_cognitive_services()
                            sources.append({"title": "Log Analytics (AzureDiagnostics)", "content": f"## Logs:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
                    elif fname == "self.query_azure_diagnostics_ai_search":
                        try:
                            sql_results = self.query_azure_diagnostics_ai_search()
                            sources.append({"title": "Log Analytics (AzureDiagnostics)", "content": f"## Logs:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
                    elif fname == "self.query_azure_diagnostics_sql":
                        try:
                            sql_results = self.query_azure_diagnostics_sql()
                            sources.append({"title": "Log Analytics (AzureDiagnostics)", "content": f"## Logs:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
                    elif fname == "self.query_azure_metrics":
                        try:
                            sql_results = self.query_azure_metrics()
                            sources.append({"title": "Log Analytics (AzureMetrics)", "content": f"## Logs:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
                    elif fname == "self.query_usage":
                        try:
                            sql_results = self.query_usage()
                            sources.append({"title": "Log Analytics (Usage)", "content": f"## Logs:\n{sql_results}\n"})
                        except Exception as se:
                            logger.error(f"Search query failed for Log Analytics: {se}")
            return sources
        except Exception as e:
            logger.error(f"Error in get_chat_completion: {e}")
            raise

    def query_appservice_audit_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AppServiceAuditLogs\n"
            "| extend Status = coalesce(toint(column_ifexists('ResultType','')), toint(column_ifexists('StatusCode','')), toint(column_ifexists('scStatus','')))\n"
            "| extend ResultDescription = tostring(column_ifexists('ResultDescription',''))\n"
            "| where (isnotnull(Status) and Status >= 500) or ResultDescription has_any ('fail','error','exception','critical')\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)

    def query_appservice_console_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AppServiceConsoleLogs\n"
            "| extend Level = tostring(column_ifexists('Level','')), Message = tostring(column_ifexists('Message',''))\n"
            "| where Level in ('Error','Critical','Fatal') or Message has_any ('ERROR','Error','Exception','Critical','Fail')\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)
    
    def query_appservice_http_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "union isfuzzy=true AppServiceHTTPLogs, AppServiceHttpLogs\n"
            "| extend Status = coalesce(toint(column_ifexists('scStatus','')), toint(column_ifexists('StatusCode','')), toint(column_ifexists('status','')), toint(column_ifexists('httpStatusCode','')))\n"
            "| where isnotnull(Status) and Status >= 500\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)
    
    def query_appservice_platform_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AppServicePlatformLogs\n"
            "| extend Level = tostring(column_ifexists('Level','')), Status = toint(column_ifexists('StatusCode','')), ResultDescription = tostring(column_ifexists('ResultDescription',''))\n"
            "| where Level in ('Error','Critical','Fatal') or (isnotnull(Status) and Status >= 500) or ResultDescription has_any ('fail','error','exception','critical')\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)

    def query_azure_diagnostics_cognitive_services(self) -> List[Dict[str, Any]]:
        kusto = (
            "AzureDiagnostics\n"
            "| where ResourceProvider == 'MICROSOFT.COGNITIVESERVICES'\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)

    def query_azure_diagnostics_ai_search(self) -> List[Dict[str, Any]]:
        kusto = (
            "AzureDiagnostics\n"
            "| where ResourceProvider == 'MICROSOFT.SEARCH'\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)
    
    def query_azure_diagnostics_sql(self) -> List[Dict[str, Any]]:
        kusto = (
            "AzureDiagnostics\n"
            "| where ResourceProvider == 'MICROSOFT.SQL'\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)
    
    def query_azure_metrics(self) -> List[Dict[str, Any]]:
        kusto = (
            "AzureMetrics\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)

    def query_usage(self) -> List[Dict[str, Any]]:
        kusto = (
            "Usage\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| sort by TimeGenerated desc"
        )
        rows = self.query(kusto)
        return self.rows_to_markdown_table(rows)

log_analytics_service = LogAnalyticsService()
