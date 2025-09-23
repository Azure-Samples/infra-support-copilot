#!/usr/bin/env python3
"""
Azure SQL Database user creation script with Azure AD authentication.
This script replaces the PowerShell Ensure-DbUser function with a Python implementation
that uses Authentication=ActiveDirectoryDefault for reliable Azure CLI token-based authentication.
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict

import pyodbc
from azure.core.exceptions import ClientAuthenticationError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_env_file(env_path: str = ".env") -> Dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}
    env_file = Path(env_path)
    
    if not env_file.exists():
        logger.warning(f"Environment file {env_path} not found")
        return env_vars
    
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    
    return env_vars


def get_current_principal() -> Optional[str]:
    """
    Get current principal (Service Principal or User).
    In CI environments, returns Service Principal Object ID.
    """
    # Check if running in CI environment
    ci_indicators = ['CI', 'GITHUB_ACTIONS', 'TF_BUILD']
    is_ci = any(os.getenv(indicator) == 'true' for indicator in ci_indicators)
    
    if is_ci:
        logger.info("CI environment detected - using Service Principal authentication")
        try:
            # Try to get service principal info from Azure CLI
            import subprocess
            import json
            
            # Get account info
            result = subprocess.run(
                ['az', 'account', 'show', '--query', 'user', '-o', 'json'],
                capture_output=True, text=True, check=True
            )
            account_info = json.loads(result.stdout)
            
            if account_info.get('type') == 'servicePrincipal':
                logger.info(f"Service Principal detected: {account_info['name']}")
                return account_info['name']  # This is the Object ID
            
        except Exception as e:
            logger.warning(f"Could not determine current principal in CI environment: {e}")
            return None
    
    return None  # For local environments, use App Service name


def build_user_creation_sql(app_name: str, is_service_principal: bool = False) -> str:
    """
    Build T-SQL for creating user and assigning roles.
    
    Args:
        app_name: App Service name or Service Principal Object ID
        is_service_principal: Whether the principal is a Service Principal
    
    Returns:
        T-SQL command string
    """
    # Escape SQL identifier
    escaped_name = app_name.replace(']', ']]')
    identifier = f"[{escaped_name}]"
    
    principal_type = "Service Principal" if is_service_principal else "App Service Managed Identity"
    
    sql = f"""-- Create {principal_type} user: {app_name}
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{app_name}')
BEGIN
    CREATE USER {identifier} FROM EXTERNAL PROVIDER;
    PRINT 'Created user: {app_name}';
END
ELSE
BEGIN
    PRINT 'User already exists: {app_name}';
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.database_role_members rm
    JOIN sys.database_principals r ON rm.role_principal_id = r.principal_id
    JOIN sys.database_principals m ON rm.member_principal_id = m.principal_id
    WHERE r.name = N'db_datareader' AND m.name = N'{app_name}'
)
BEGIN
    ALTER ROLE db_datareader ADD MEMBER {identifier};
    PRINT 'Added to db_datareader: {app_name}';
END
ELSE
BEGIN
    PRINT 'Already member of db_datareader: {app_name}';
END;"""
    
    return sql


def get_sql_connection_string(server: str, database: str) -> str:
    """
    Build SQL connection string with Azure AD authentication.
    
    Args:
        server: SQL Server name
        database: Database name
    
    Returns:
        Connection string
    """
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Authentication=ActiveDirectoryDefault;"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )


def ensure_db_user(server: str, database: str, app_name: str, is_service_principal: bool = False) -> bool:
    """
    Ensure database user exists and has proper roles.
    
    Args:
        server: SQL Server name  
        database: Database name
        app_name: App Service name or Service Principal Object ID
        is_service_principal: Whether the principal is a Service Principal
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Creating database user for: {app_name}")
        principal_type = "Service Principal (CI Environment)" if is_service_principal else "App Service Managed Identity"
        logger.info(f"  Type: {principal_type}")
        
        # Build connection string
        conn_string = get_sql_connection_string(server, database)
        logger.info(f"  Connecting to: {server}/{database}")
        
        # Build SQL command
        sql_command = build_user_creation_sql(app_name, is_service_principal)
        
        # Connect and execute
        with pyodbc.connect(conn_string) as conn:
            cursor = conn.cursor()
            
            # Execute SQL in parts to handle PRINT statements
            for statement in sql_command.split('\n\n'):
                if statement.strip():
                    try:
                        cursor.execute(statement)
                        # Try to fetch any messages
                        while cursor.nextset():
                            pass
                    except pyodbc.Error as e:
                        # Check if it's just an informational message
                        if "PRINT" not in statement:
                            raise
            
            conn.commit()
            logger.info("Database user creation completed successfully")
            return True
            
    except ClientAuthenticationError as e:
        logger.error(f"Azure authentication failed: {e}")
        logger.error("Make sure you are logged in with 'az login' and have proper permissions")
        return False
    except pyodbc.Error as e:
        logger.error(f"SQL Server error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Ensure Azure SQL Database user exists with proper roles"
    )
    parser.add_argument(
        "--server", 
        help="SQL Server name (e.g., myserver.database.windows.net)"
    )
    parser.add_argument(
        "--database", 
        help="Database name"
    )
    parser.add_argument(
        "--app-name", 
        help="App Service name or Service Principal Object ID"
    )
    parser.add_argument(
        "--env-file", 
        default=".env",
        help="Path to environment file (default: .env)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load environment variables
    env_vars = load_env_file(args.env_file)
    
    # Get required parameters
    server = args.server or env_vars.get('AZURE_SQL_SERVER')
    database = args.database or env_vars.get('AZURE_SQL_DATABASE_NAME') 
    app_service_name = args.app_name or env_vars.get('AZURE_APP_SERVICE_NAME')
    
    if not all([server, database, app_service_name]):
        logger.error("Missing required parameters:")
        if not server:
            logger.error("  --server or AZURE_SQL_SERVER environment variable")
        if not database:
            logger.error("  --database or AZURE_SQL_DATABASE_NAME environment variable")
        if not app_service_name:
            logger.error("  --app-name or AZURE_APP_SERVICE_NAME environment variable")
        sys.exit(1)
    
    # Determine if we're using Service Principal (CI environment)
    current_principal = get_current_principal()
    if current_principal:
        logger.info(f"CI Environment: Using Service Principal ID instead of App Service name")
        logger.info(f"  App Service Name: {app_service_name}")
        logger.info(f"  Service Principal: {current_principal}")
        principal_name = current_principal
        is_service_principal = True
    else:
        principal_name = app_service_name
        is_service_principal = False
    
    # Ensure database user
    success = ensure_db_user(server, database, principal_name, is_service_principal)
    
    if success:
        logger.info("Done.")
        sys.exit(0)
    else:
        logger.error("Failed to ensure database user")
        sys.exit(1)


if __name__ == "__main__":
    main()