#!/usr/bin/env python3
"""
Database user creation script for Azure SQL Database.
Creates managed identity users for Azure App Service or Service Principal authentication.
"""

import os
import sys
import json
import subprocess
import pyodbc
from typing import Dict, Optional
import argparse


def write_section(msg: str) -> None:
    """Print a section header."""
    print(f"\n=== {msg} ===", flush=True)


def is_ci_environment() -> bool:
    """Detect if running in CI environment (GitHub Actions, Azure DevOps, etc.)."""
    ci_indicators = ['CI', 'GITHUB_ACTIONS', 'TF_BUILD']
    return any(os.getenv(var) == 'true' for var in ci_indicators)

def get_best_odbc_driver() -> str:
    """Get the best available ODBC driver that supports ActiveDirectoryDefault."""
    drivers = pyodbc.drivers()
    print(f"Available ODBC drivers: {drivers}")
    
    # Prefer ODBC Driver 18 (supports ActiveDirectoryDefault)
    for driver in drivers:
        if "ODBC Driver 18 for SQL Server" in driver:
            print(f"Using: {driver}")
            return driver
    
    # Fall back to ODBC Driver 17 (limited auth support)
    for driver in drivers:
        if "ODBC Driver 17 for SQL Server" in driver:
            print(f"WARNING: Using {driver} - ActiveDirectoryDefault may not be supported")
            return driver
    
    # Last resort
    for driver in drivers:
        if "SQL Server" in driver:
            print(f"WARNING: Using {driver} - limited authentication support")
            return driver
    
    raise RuntimeError("No compatible SQL Server ODBC driver found")

def get_current_principal() -> Optional[str]:
    """Get current principal (Service Principal in CI, None for local)."""
    if not is_ci_environment():
        return None

    try:
        is_windows = os.name == 'nt'
        if is_windows:
            # Use PowerShell on Windows for better compatibility
            cmd = ['pwsh', '-Command', 'az account show --query user -o json']
        else:
            cmd = ['az', 'account', 'show', '--query', 'user', '-o', 'json']

        result = subprocess.run(
            cmd,
            capture_output=True, text=True, check=True
        )
        account_info = json.loads(result.stdout)
        if account_info.get('type') == 'servicePrincipal':
            print(f"Service Principal detected: {account_info['name']}")
            return account_info['name']  # Service Principal Object ID
            
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Could not determine current principal in CI environment: {e}")
    
    return None

def get_required_values(env_map: Dict[str, str]) -> Dict[str, str]:
    """Extract and validate required configuration values."""
    required = ['AZURE_APP_SERVICE_NAME', 'AZURE_SQL_SERVER', 'AZURE_SQL_DATABASE_NAME']
    
    for key in required:
        if not env_map.get(key):
            raise ValueError(f"Missing {key} in .env file")
    
    # Use Service Principal in CI environment
    is_ci = is_ci_environment()
    principal_name = env_map['AZURE_APP_SERVICE_NAME']
    
    if is_ci:
        current_principal = get_current_principal()
        if current_principal:
            print("CI Environment: Using Service Principal ID instead of App Service name")
            print(f"  App Service Name: {env_map['AZURE_APP_SERVICE_NAME']}")
            print(f"  Service Principal: {current_principal}")
            principal_name = current_principal
    
    return {
        'app_name': principal_name,
        'sql_server': env_map['AZURE_SQL_SERVER'],
        'database': env_map['AZURE_SQL_DATABASE_NAME'],
        'is_service_principal': is_ci
    }


def build_tsql(app_name: str, is_service_principal: bool = False) -> str:
    """Build T-SQL script to create database user and assign permissions."""
    # Escape square brackets in the name
    escaped_name = app_name.replace(']', ']]')
    identifier = f"[{escaped_name}]"
    
    principal_type = "Service Principal" if is_service_principal else "App Service Managed Identity"
    
    return f"""-- Create {principal_type} user: {app_name}
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

def execute_sql(server: str, database: str, query: str) -> None:
    """Execute SQL query using Azure Active Directory Default authentication."""
    # Build connection string with Azure AD Default authentication
    driver = get_best_odbc_driver()
    print(f"Using ODBC Driver: {driver}")

    connection_string = (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    
    is_ci = is_ci_environment()
    
    print(f"Connecting to: {server}/{database}")
    print(f"Authentication: ActiveDirectoryDefault")
    print(f"CI Environment: {is_ci}")
    
    try:
        with pyodbc.connect(connection_string) as conn:
            cursor = conn.cursor()
            
            # Execute the T-SQL script
            print("\nExecuting T-SQL script...")
            cursor.execute(query)
            
            # Process any messages/prints from SQL Server
            while cursor.nextset():
                pass
            
            conn.commit()
            print("SQL execution completed successfully.")
            
    except pyodbc.Error as e:
        error_msg = str(e)
        
        if is_ci and "AADSTS" in error_msg:
            print("\nCI Environment Error - This might be due to:")
            print("1. Service Principal not having proper permissions")
            print("2. Azure CLI not properly authenticated")
            print("3. Service Principal not being granted access to the database")
            
        raise RuntimeError(f"Database connection failed: {error_msg}")


def ensure_db_user(info: Dict[str, str]) -> None:
    """Create database user with proper permissions."""
    app_name = info['app_name']
    is_service_principal = info['is_service_principal']
    
    print(f"Creating database user for: {app_name}")
    if is_service_principal:
        print("  Type: Service Principal (CI Environment)")
    else:
        print("  Type: App Service Managed Identity")
    
    query = build_tsql(app_name, is_service_principal)
    
    execute_sql(
        server=info['sql_server'],
        database=info['database'],
        query=query
    )
    
    print("Database user creation completed successfully!")


def main():
    """Main execution function."""
    try:
        write_section("Loading environment configuration")

        parser = argparse.ArgumentParser(description="Ensure Azure SQL DB user exists")
        parser.add_argument("--server", dest="AZURE_SQL_SERVER", required=True, help="Azure SQL Server name")
        parser.add_argument("--database", dest="AZURE_SQL_DATABASE_NAME", required=True, help="Azure SQL Database name")
        parser.add_argument("--app-name", dest="AZURE_APP_SERVICE_NAME", required=True, help="App Service or Principal name")
        args = parser.parse_args()

        env_map = {
            "AZURE_SQL_SERVER": args.AZURE_SQL_SERVER,
            "AZURE_SQL_DATABASE_NAME": args.AZURE_SQL_DATABASE_NAME,
            "AZURE_APP_SERVICE_NAME": args.AZURE_APP_SERVICE_NAME,
        }
        
        if not env_map:
            raise ValueError("No .env file found or file is empty")
        
        info = get_required_values(env_map)
        
        write_section(f"Target: {info['sql_server']}/{info['database']} (AppUser: {info['app_name']})")
        
        ensure_db_user(info)
        
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
