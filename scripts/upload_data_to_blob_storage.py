import os
import dotenv
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential

dotenv.load_dotenv()

STORAGE_ACCOUNT_URL = "https://" + os.getenv("AZURE_STORAGE_ACCOUNT_NAME") + ".blob.core.windows.net"
CREDENTIAL = DefaultAzureCredential()

blob_service_client = BlobServiceClient(account_url=STORAGE_ACCOUNT_URL, credential=CREDENTIAL)

import hashlib

container = "inventories"
doc = "Sample_Server_Inventories.json"
container_client = blob_service_client.get_container_client(container)
docid = hashlib.sha256(doc.encode("utf-8")).hexdigest()
with open(f"docs/{doc}", "rb") as data:
    print(f"Uploading {doc} to {container}/{doc} with docid={docid}")
    container_client.upload_blob(
        name=doc,
        data=data,
        overwrite=True,
        metadata={"docid": docid}
    )

container = "incidents"
folder = "docs/incidents"
container_client = blob_service_client.get_container_client(container)
for root, _, files in os.walk(folder):
    for file in files:
        if file == "inc_format.md":
            continue
        file_path = os.path.join(root, file)
        blob_path = os.path.relpath(file_path, folder).replace("\\", "/")
        docid = hashlib.sha256(blob_path.encode("utf-8")).hexdigest()
        with open(file_path, "rb") as data:
            print(f"Uploading {file_path} to {container}/{blob_path} with docid={docid}")
            container_client.upload_blob(
                name=blob_path,
                data=data,
                overwrite=True,
                metadata={"docid": docid}
            )
