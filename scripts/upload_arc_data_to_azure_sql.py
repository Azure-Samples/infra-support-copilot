from __future__ import annotations

import json
import os
from dotenv import load_dotenv
import sys
import datetime as dt
import struct
from pathlib import Path
from typing import Any, Iterable

import pyodbc  # type: ignore
from azure.identity import DefaultAzureCredential

ROOT = Path(__file__).resolve().parents[1]
ARC_DIR = ROOT / "docs" / "arc"

VM_FILE = ARC_DIR / "rscgrf_get_azure_virtual_machines.json"
NIC_FILE = ARC_DIR / "rscgrf_get_azure_network_interfaces.json"
SW_FILE = ARC_DIR / "logana_get_install_software.json"

SCOPE = "https://database.windows.net/.default"

load_dotenv()

def env(name: str, default: str | None = None) -> str:
	v = os.getenv(name, default)
	if not v:
		raise RuntimeError(f"Environment variable {name} is not set")
	return v


def get_connection() -> pyodbc.Connection:
	"""
	Obtain an Azure SQL connection using an AAD access token.
	"""
	server = os.getenv("AZURE_SQL_SERVER")
	database = os.getenv("AZURE_SQL_DATABASE_NAME")
	if not server or not database:
		raise RuntimeError("Set AZURE_SQL_SERVER & AZURE_SQL_DATABASE")

	# Normalize server (allow user to omit tcp: prefix)
	server = server.replace("tcp:", "")

	credential = DefaultAzureCredential(exclude_interactive_browser_credential=False)
	token = credential.get_token(SCOPE)

	# Build token structure: 4-byte length (little endian) + UTF-16-LE token bytes
	token_bytes = token.token.encode("utf-16-le")
	token_struct = struct.pack("=i", len(token_bytes)) + token_bytes
	attrs_before = {1256: token_struct}  # 1256 = SQL_COPT_SS_ACCESS_TOKEN

	conn_str = (
		"DRIVER={ODBC Driver 18 for SQL Server};"
		f"SERVER=tcp:{server},1433;DATABASE={database};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
	)

	return pyodbc.connect(conn_str, attrs_before=attrs_before)

def ensure_tables(cursor: pyodbc.Cursor) -> None:
	"""Create tables if they do not exist."""
	cursor.execute(
		"""
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'virtual_machines')
BEGIN
	CREATE TABLE dbo.virtual_machines (
		resource_id           NVARCHAR(512) NOT NULL PRIMARY KEY,
		name                  NVARCHAR(128),
		subscription_id       UNIQUEIDENTIFIER NULL,
		resource_group        NVARCHAR(128),
		location              NVARCHAR(64),
		vm_size               NVARCHAR(64),
		os_type               NVARCHAR(32),
		os_name               NVARCHAR(128),
		os_version            NVARCHAR(64),
		provisioning_state    NVARCHAR(32),
		priority              NVARCHAR(32),
		time_created          DATETIME2,
		power_state           NVARCHAR(64),
		admin_username        NVARCHAR(64),
		server_type_tag       NVARCHAR(128),
		tags_json             NVARCHAR(MAX),
		identity_principal_id UNIQUEIDENTIFIER NULL
	);
END
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'network_interfaces')
BEGIN
	CREATE TABLE dbo.network_interfaces (
		resource_id        NVARCHAR(512) NOT NULL PRIMARY KEY,
		name               NVARCHAR(128),
		subscription_id    UNIQUEIDENTIFIER NULL,
		resource_group     NVARCHAR(128),
		location           NVARCHAR(64),
		mac_address        NVARCHAR(32),
		private_ip         NVARCHAR(64),
		allocation_method  NVARCHAR(32),
		accelerated        BIT,
		primary_flag       BIT,
		vm_resource_id     NVARCHAR(512) NULL
			REFERENCES dbo.virtual_machines(resource_id)
	);
END
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'installed_software')
BEGIN
	CREATE TABLE dbo.installed_software (
		id              INT IDENTITY(1,1) PRIMARY KEY,
		computer_name   NVARCHAR(256) NOT NULL,
		software_name   NVARCHAR(512) NOT NULL,
		current_version NVARCHAR(256),
		publisher       NVARCHAR(512)
	);
	CREATE INDEX IX_installed_software_computer ON dbo.installed_software(computer_name);
	CREATE INDEX IX_installed_software_name ON dbo.installed_software(software_name);
END
"""
	)


def parse_time(value: Any) -> dt.datetime | None:
	if not value:
		return None
	try:
		return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
	except Exception:
		return None


def load_json_array(path: Path) -> list[dict[str, Any]]:
	if not path.exists():
		print(f"WARN: {path} does not exist", file=sys.stderr)
		return []
	with path.open("r", encoding="utf-8") as f:
		return json.load(f)


def upsert_virtual_machines(cursor: pyodbc.Cursor, rows: Iterable[dict[str, Any]]) -> int:
	count = 0
	for row in rows:
		props = row.get("properties", {})
		ext = props.get("extended", {})
		instance_view = ext.get("instanceView", {})
		storage_profile = props.get("storageProfile", {})
		os_disk = storage_profile.get("osDisk", {})
		power_state = instance_view.get("powerState", {}).get("displayStatus")
		os_name = instance_view.get("computerName") and instance_view.get("osName") or None
		os_version = instance_view.get("osVersion")
		# fallback
		if not os_name:
			os_name = os_disk.get("osType")
		identity = row.get("identity") or {}
		tags = row.get("tags") or {}
		server_type_tag = None
		if tags:
			server_type_tag = tags.get("ServerType")

		cursor.execute(
			"""
IF EXISTS (SELECT 1 FROM dbo.virtual_machines WHERE resource_id = ?)
	UPDATE dbo.virtual_machines SET
		name=?, subscription_id=TRY_CONVERT(uniqueidentifier, ?), resource_group=?, location=?,
		vm_size=?, os_type=?, os_name=?, os_version=?, provisioning_state=?, priority=?,
		time_created=?, power_state=?, admin_username=?, server_type_tag=?, tags_json=?, identity_principal_id=TRY_CONVERT(uniqueidentifier, ?)
	WHERE resource_id=?
ELSE
	INSERT INTO dbo.virtual_machines (
		resource_id,name,subscription_id,resource_group,location,vm_size,os_type,os_name,os_version,
		provisioning_state,priority,time_created,power_state,admin_username,server_type_tag,tags_json,identity_principal_id
	) VALUES (
		?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
	);
""",
			row.get("id"),  # for UPDATE match
			row.get("name"),
			row.get("subscriptionId"),
			row.get("resourceGroup"),
			row.get("location"),
			(props.get("hardwareProfile") or {}).get("vmSize"),
			os_disk.get("osType"),
			os_name,
			os_version,
			props.get("provisioningState"),
			props.get("priority"),
			parse_time(props.get("timeCreated")),
			power_state,
			(props.get("osProfile") or {}).get("adminUsername"),
			server_type_tag,
			json.dumps(tags, ensure_ascii=False) if tags else None,
			identity.get("principalId"),
			row.get("id"),  # WHERE resource_id
			# INSERT values (repeat in order)
			row.get("id"),
			row.get("name"),
			row.get("subscriptionId"),
			row.get("resourceGroup"),
			row.get("location"),
			(props.get("hardwareProfile") or {}).get("vmSize"),
			os_disk.get("osType"),
			os_name,
			os_version,
			props.get("provisioningState"),
			props.get("priority"),
			parse_time(props.get("timeCreated")),
			power_state,
			(props.get("osProfile") or {}).get("adminUsername"),
			server_type_tag,
			json.dumps(tags, ensure_ascii=False) if tags else None,
			identity.get("principalId"),
		)
		count += 1
	return count


def upsert_network_interfaces(cursor: pyodbc.Cursor, rows: Iterable[dict[str, Any]]) -> int:
	count = 0
	for row in rows:
		props = row.get("properties", {})
		ip_configs = props.get("ipConfigurations") or []
		ip_conf = ip_configs[0] if ip_configs else {}
		ip_props = ip_conf.get("properties", {})
		cursor.execute(
			"""
IF EXISTS (SELECT 1 FROM dbo.network_interfaces WHERE resource_id = ?)
	UPDATE dbo.network_interfaces SET
		name=?, subscription_id=TRY_CONVERT(uniqueidentifier, ?), resource_group=?, location=?, mac_address=?, private_ip=?,
		allocation_method=?, accelerated=?, primary_flag=?, vm_resource_id=?
	WHERE resource_id=?
ELSE
	INSERT INTO dbo.network_interfaces (
		resource_id,name,subscription_id,resource_group,location,mac_address,private_ip,allocation_method,accelerated,primary_flag,vm_resource_id
	) VALUES (?,?,?,?,?,?,?,?,?,?,?);
""",
			row.get("id"),
			row.get("name"),
			row.get("subscriptionId"),
			row.get("resourceGroup"),
			row.get("location"),
			props.get("macAddress"),
			ip_props.get("privateIPAddress"),
			ip_props.get("privateIPAllocationMethod") or ip_props.get("privateIPAllocationMethod"),
			1 if props.get("enableAcceleratedNetworking") else 0,
			1 if (props.get("primary") or ip_props.get("primary")) else 0,
			(props.get("virtualMachine") or {}).get("id"),
			row.get("id"),  # WHERE
			# INSERT
			row.get("id"),
			row.get("name"),
			row.get("subscriptionId"),
			row.get("resourceGroup"),
			row.get("location"),
			props.get("macAddress"),
			ip_props.get("privateIPAddress"),
			ip_props.get("privateIPAllocationMethod") or ip_props.get("privateIPAllocationMethod"),
			1 if props.get("enableAcceleratedNetworking") else 0,
			1 if (props.get("primary") or ip_props.get("primary")) else 0,
			(props.get("virtualMachine") or {}).get("id"),
		)
		count += 1
	return count


def insert_installed_software(cursor: pyodbc.Cursor, rows: Iterable[dict[str, Any]]) -> int:
	count = 0
	for row in rows:
		cursor.execute(
			"""
IF NOT EXISTS (
	SELECT 1 FROM dbo.installed_software WHERE computer_name = ? AND software_name = ? AND ISNULL(current_version,'') = ISNULL(?, '')
)
	INSERT INTO dbo.installed_software (computer_name,software_name,current_version,publisher)
	VALUES (?,?,?,?);
""",
			row.get("Computer"),
			row.get("SoftwareName"),
			row.get("CurrentVersion"),
			row.get("Computer"),
			row.get("SoftwareName"),
			row.get("CurrentVersion"),
			row.get("Publisher"),
		)
		count += cursor.rowcount if cursor.rowcount else 0
	return count


def main() -> None:
	if not VM_FILE.exists() and not NIC_FILE.exists() and not SW_FILE.exists():
		print("There is no ARC data JSON found (docs/arc/*.json)", file=sys.stderr)
		sys.exit(1)

	with get_connection() as conn:
		cursor = conn.cursor()
		ensure_tables(cursor)
		conn.commit()

		vm_rows = load_json_array(VM_FILE)
		nic_rows = load_json_array(NIC_FILE)
		# Software is large, so stream processing (bulk loading is also possible)
		sw_rows = load_json_array(SW_FILE)

		total_vm = upsert_virtual_machines(cursor, vm_rows)
		print("Virtual Machine Data Uploaded.")
		total_nic = upsert_network_interfaces(cursor, nic_rows)
		print("Network Interface Data Uploaded.")
		total_sw = insert_installed_software(cursor, sw_rows)
		print("Installed Software Data Uploaded.")
		conn.commit()

	print("Import complete:")
	print(f"  virtual_machines: {total_vm}")
	print(f"  network_interfaces: {total_nic}")
	print(f"  installed_software (only new): {total_sw}")


if __name__ == "__main__":
	main()
