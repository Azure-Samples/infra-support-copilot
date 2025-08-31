from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

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

    async def _select_service(self, condensed_query: str) -> Tuple[bool, bool, bool, bool, bool, bool, bool]:
        import json
        index_selection_prompt = (
            "Decide which log data should be searched to answer the user's request.\n"
            "Services: 'AppServiceAuditLogs', 'AppServiceConsoleLogs', 'AppServiceHTTPLogs', 'AppServicePlatformLogs', 'AzureDiagnostics', 'AzureMetrics', 'Usage'.\n"
            "Return ONLY JSON like {\"AppServiceAuditLogs\": true, \"AppServiceConsoleLogs\": false, \"AppServiceHTTPLogs\": false, \"AppServicePlatformLogs\": false, \"AzureDiagnostics\": false, \"AzureMetrics\": false, \"Usage\": false}. If unsure, set a field to true.\n"
            f"Query: {condensed_query}"
        )
        try:
            selection_response = await self.openai_client.chat.completions.create(
                messages=[{"role": "user", "content": index_selection_prompt}],
                model=self.gpt_deployment
            )
            selection_text = selection_response.choices[0].message.content.strip()
            selection = json.loads(selection_text)
            return bool(selection.get("AppServiceAuditLogs", False)), bool(selection.get("AppServiceConsoleLogs", False)), bool(selection.get("AppServiceHTTPLogs", False)), bool(selection.get("AppServicePlatformLogs", False)), bool(selection.get("AzureDiagnostics", False)), bool(selection.get("AzureMetrics", False)), bool(selection.get("Usage", False))
        except Exception as e:
            logger.warning(f"Index selection failed ({e}); defaulting to all indexes")
            return True, True, True, True, True, True, True

    
    async def get_chat_completion(self, effective_query: str):
        try:
            app_service_audit_logs, app_service_console_logs, app_service_http_logs, app_service_platform_logs, azure_diagnostics_logs, azure_metrics_logs, usage_logs = await self._select_service(effective_query)

            sources = []
            
            if app_service_audit_logs:
                sources.append({"title": "Log Analytics (App Service Audit Logs)", "content": f"## Errors:\n{self.query_appservice_audit_logs_errors()}\n"})

            if app_service_console_logs:
                sources.append({"title": "Log Analytics (App Service Console Logs)", "content": f"## Errors:\n{self.query_appservice_console_logs_errors()}\n"})

            if app_service_http_logs:
                sources.append({"title": "Log Analytics (App Service HTTP Logs)", "content": f"## Errors:\n{self.query_appservice_http_logs_errors()}\n"})

            if app_service_platform_logs:
                sources.append({"title": "Log Analytics (App Service Platform Logs)", "content": f"## Errors:\n{self.query_appservice_platform_logs_errors()}\n"})

            if azure_diagnostics_logs:
                sources.append({"title": "Log Analytics (Azure Diagnostics)", "content": f"## Errors:\n{self.query_azure_diagnostics_errors()}\n"})

            if azure_metrics_logs:
                sources.append({"title": "Log Analytics (Azure Metrics)", "content": f"## Errors:\n{self.query_azure_metrics_errors()}\n"})

            if usage_logs:
                sources.append({"title": "Log Analytics (Usage)", "content": f"## Errors:\n{self.query_usage_errors()}\n"})

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
            "| summarize count() by bin(TimeGenerated, 5m), Status\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)

    def query_appservice_console_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AppServiceConsoleLogs\n"
            "| extend Level = tostring(column_ifexists('Level','')), Message = tostring(column_ifexists('Message',''))\n"
            "| where Level in ('Error','Critical','Fatal') or Message has_any ('ERROR','Error','Exception','Critical','Fail')\n"
            "| summarize count() by bin(TimeGenerated, 5m), Level\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)
    
    def query_appservice_http_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "union isfuzzy=true AppServiceHTTPLogs, AppServiceHttpLogs\n"
            "| extend Status = coalesce(toint(column_ifexists('scStatus','')), toint(column_ifexists('StatusCode','')), toint(column_ifexists('status','')), toint(column_ifexists('httpStatusCode','')))\n"
            "| where isnotnull(Status) and Status >= 500\n"
            "| summarize count() by bin(TimeGenerated, 5m), Status\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)
    
    def query_appservice_platform_logs_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AppServicePlatformLogs\n"
            "| extend Level = tostring(column_ifexists('Level','')), Status = toint(column_ifexists('StatusCode','')), ResultDescription = tostring(column_ifexists('ResultDescription',''))\n"
            "| where Level in ('Error','Critical','Fatal') or (isnotnull(Status) and Status >= 500) or ResultDescription has_any ('fail','error','exception','critical')\n"
            "| summarize count() by bin(TimeGenerated, 5m), Level\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)

    def query_azure_diagnostics_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AzureDiagnostics\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| extend Level = tostring(column_ifexists('Level','')), Status = toint(column_ifexists('StatusCode','')), ResultDescription = tostring(column_ifexists('ResultDescription',''))\n"
            "| summarize count() by bin(TimeGenerated, 5m), Level, Status, ResultDescription\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)
    
    def query_azure_metrics_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "AzureMetrics\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| extend Level = tostring(column_ifexists('Level','')), Status = toint(column_ifexists('StatusCode','')), ResultDescription = tostring(column_ifexists('ResultDescription',''))\n"
            "| summarize count() by bin(TimeGenerated, 5m), Level, Status, ResultDescription\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)

    def query_usage_errors(self) -> List[Dict[str, Any]]:
        kusto = (
            "Usage\n"
            "| where TimeGenerated >= ago(24h)\n"
            "| extend Level = tostring(column_ifexists('Level','')), Status = toint(column_ifexists('StatusCode','')), ResultDescription = tostring(column_ifexists('ResultDescription',''))\n"
            "| summarize count() by bin(TimeGenerated, 5m), Level, Status, ResultDescription\n"
            "| sort by TimeGenerated desc"
        )
        return self.query(kusto)

log_analytics_service = LogAnalyticsService()
