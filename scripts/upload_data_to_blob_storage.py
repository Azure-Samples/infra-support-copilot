import os
import hashlib
import time
import traceback
from datetime import datetime
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential


def _ts() -> str:
    """Return current timestamp string with millisecond precision."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def log(msg: str) -> None:
    """Print log line with timestamp and flush immediately."""
    print(f"[{_ts()}] {msg}", flush=True)

overall_start = time.perf_counter()
log("Script start: upload_data_to_blob_storage")

load_dotenv()
log("Loaded .env (if present)")

storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "")
STORAGE_ACCOUNT_URL = f"https://{storage_account_name}.blob.core.windows.net" if storage_account_name else ""
if storage_account_name:
    log(f"Using storage account: {storage_account_name}")
else:
    log("Warning: AZURE_STORAGE_ACCOUNT_NAME is empty")

cred_start = time.perf_counter()
CREDENTIAL = DefaultAzureCredential()
log(f"Initialized DefaultAzureCredential in {(time.perf_counter() - cred_start):.3f}s")

client_start = time.perf_counter()
blob_service_client = BlobServiceClient(account_url=STORAGE_ACCOUNT_URL, credential=CREDENTIAL)
log(f"Connected to Blob Storage (client init {(time.perf_counter() - client_start):.3f}s)")
container = "inventories"
doc = "Sample_Server_Inventories.json"

container_client = blob_service_client.get_container_client(container)
log(f"Got container client for '{container}'")
docid = hashlib.sha256(doc.encode("utf-8")).hexdigest()
doc_path = os.path.join("docs", doc)
size = os.path.getsize(doc_path) if os.path.isfile(doc_path) else None
if size is None:
    log(f"Warning: file not found -> {doc_path}")
else:
    try:
        log(f"Uploading {doc_path} -> {container}/{doc} (docid={docid}, size={size} bytes)")
        up_start = time.perf_counter()
        with open(doc_path, "rb") as data:
            container_client.upload_blob(
                name=doc,
                data=data,
                overwrite=True,
                metadata={"docid": docid}
            )
        elapsed = time.perf_counter() - up_start
        mbps = (size / (1024 * 1024)) / elapsed if elapsed > 0 else float("inf")
        log(f"Uploaded {doc} in {elapsed:.3f}s ({size} bytes, {mbps:.2f} MB/s)")
    except Exception as e:
        log(f"ERROR uploading {doc_path}: {e}")
        traceback.print_exc()

container = "incidents"
folder = "docs/incidents"
container_client = blob_service_client.get_container_client(container)
log(f"Got container client for '{container}' (folder={folder})")

total_files = 0
uploaded_files = 0
failed_files = 0
total_bytes = 0
walk_start = time.perf_counter()
for root, _, files in os.walk(folder):
    for file in files:
        if file == "inc_format.md":
            log(f"Skip template file: {os.path.join(root, file)}")
            continue
        file_path = os.path.join(root, file)
        blob_path = os.path.relpath(file_path, folder).replace("\\", "/")
        docid = hashlib.sha256(blob_path.encode("utf-8")).hexdigest()
        size = os.path.getsize(file_path) if os.path.isfile(file_path) else None
        total_files += 1
        if size is None:
            log(f"Warning: file not found -> {file_path}")
            failed_files += 1
            continue
        try:
            log(f"Uploading {file_path} -> {container}/{blob_path} (docid={docid}, size={size} bytes)")
            up_start = time.perf_counter()
            with open(file_path, "rb") as data:
                container_client.upload_blob(
                    name=blob_path,
                    data=data,
                    overwrite=True,
                    metadata={"docid": docid}
                )
            elapsed = time.perf_counter() - up_start
            mbps = (size / (1024 * 1024)) / elapsed if elapsed > 0 else float("inf")
            log(f"Uploaded {blob_path} in {elapsed:.3f}s ({size} bytes, {mbps:.2f} MB/s)")
            uploaded_files += 1
            total_bytes += size
        except Exception as e:
            log(f"ERROR uploading {file_path}: {e}")
            traceback.print_exc()
            failed_files += 1

walk_elapsed = time.perf_counter() - walk_start
log(f"File enumeration and upload loop completed in {walk_elapsed:.3f}s")

overall_elapsed = time.perf_counter() - overall_start
avg_mbps = (total_bytes / (1024 * 1024)) / overall_elapsed if overall_elapsed > 0 else 0.0
log(
    "Summary: "
    f"success={uploaded_files}, failed={failed_files}, total_files_seen={total_files}, "
    f"bytes_uploaded={total_bytes} ({total_bytes/(1024*1024):.2f} MB), "
    f"overall_time={overall_elapsed:.3f}s, avg_throughput={avg_mbps:.2f} MB/s"
)

log("Script end: upload_data_to_blob_storage")
