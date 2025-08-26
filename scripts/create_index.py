import os
from dotenv import load_dotenv
import requests  # type: ignore[import-untyped]
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import SearchIndexer, FieldMapping
from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential

load_dotenv()

search_service_name = os.getenv("AZURE_SEARCH_SERVICE_NAME", "")
search_service_endpoint = f"https://{search_service_name}.search.windows.net" if search_service_name else ""

storage_account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
storage_account_resource_id = os.getenv("AZURE_STORAGE_ACCOUNT_RESOURCE_ID") 

credential = DefaultAzureCredential()
index_client = SearchIndexClient(endpoint=search_service_endpoint, credential=credential)
indexer_client = SearchIndexerClient(endpoint=search_service_endpoint, credential=credential)

def create_data_source_via_rest(data_source_name, search_service_endpoint, credential, storage_account_resource_id, container_name):
    url = f"{search_service_endpoint}/datasources/{data_source_name}?api-version=2024-07-01"
    token = credential.get_token("https://search.azure.com/.default").token
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data_source_definition = {
        "name": data_source_name,
        "type": "azureblob",
        "credentials": {
            "connectionString": f"ResourceId={storage_account_resource_id};"
        },
        "container": {
            "name": container_name
        }
    }
    response = requests.put(url, headers=headers, json=data_source_definition)
    if response.status_code in [200, 201]:
        print(f"Created data source: {data_source_name}")
        return True
    elif response.status_code == 409:
        print(f"Data source {data_source_name} already exists.")
        return True
    else:
        print(f"Error creating data source: {response.status_code} - {response.text}")
        return False

def create_index_via_rest(index_name, search_service_endpoint, credential):
    """Create index via REST API"""
    url = f"{search_service_endpoint}/indexes/{index_name}?api-version=2024-07-01"
    token = credential.get_token("https://search.azure.com/.default").token
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    index_definition = {
        "name": index_name,
        "fields": [
            {
                "name": "docid",
                "type": "Edm.String",
                "key": True,
                "filterable": True,
                "sortable": True,
                "searchable": True,
                "retrievable": True
            },
            {
                "name": "content", 
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "sortable": False,
                "facetable": False,
                "retrievable": True,
                "analyzer": "ja.lucene"
            },
            {
                "name": "metadata_storage_name",
                "type": "Edm.String", 
                "filterable": True,
                "sortable": True,
                "searchable": True,
                "retrievable": True
            },
            {
                "name": "metadata_storage_path",
                "type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "searchable": True,
                "retrievable": True
            },
            {
                "name": "embedding",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "filterable": False,
                "sortable": False,
                "facetable": False,
                "retrievable": True,
                "dimensions": 1536,
                "vectorSearchProfile": "default-vector-profile"
            }
        ],
        "vectorSearch": {
            "algorithms": [
                {
                    "name": "default-hnsw-algorithm",
                    "kind": "hnsw",
                    "hnswParameters": {
                        "m": 4,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine"
                    }
                }
            ],
            "profiles": [
                {
                    "name": "default-vector-profile",
                    "algorithm": "default-hnsw-algorithm"
                }
            ]
        },
        "semantic": {
            "configurations": [
                {
                    "name": f"{index_name}-semantic-configuration",
                    "prioritizedFields": {
                        "titleField": {
                            "fieldName": "metadata_storage_name"
                        },
                        "prioritizedContentFields": [
                            {
                                "fieldName": "content"
                            }
                        ],
                        "prioritizedKeywordsFields": [
                            {
                                "fieldName": "metadata_storage_path"
                            }
                        ]
                    }
                }
            ]
        }
    }
    
    response = requests.put(url, headers=headers, json=index_definition)
    if response.status_code in [200, 201]:
        return True
    else:
        print(f"Error creating index: {response.status_code} - {response.text}")
        return False

containers = [
    "inventories",
    "incidents"
]

for container in containers:
    # 1. Create data source via REST API (User Assigned Managed Identity)
    data_source_name = f"ds-{container}"
    storage_account_resource_id = f"/subscriptions/{os.getenv('AZURE_SUBSCRIPTION_ID')}/resourceGroups/rg-{os.getenv('AZURE_ENV_NAME')}/providers/Microsoft.Storage/storageAccounts/{storage_account_name}"
    if not create_data_source_via_rest(data_source_name, search_service_endpoint, credential, storage_account_resource_id, container):
        print(f"Failed to create data source: {data_source_name}")

    # 2. Create index
    index_name = f"index-{container}"
    index_created = False
    try:
        if create_index_via_rest(index_name, search_service_endpoint, credential):
            print(f"Created index: {index_name}")
            index_created = True
        else:
            print(f"Failed to create index: {index_name}")
    except Exception as e:
        print(f"Index {index_name} might already exist or error occurred: {e}")

    if not index_created:
        print(f"Skipping indexer creation for {container} due to index creation failure")

    # 3. Create indexer
    indexer_name = f"indexer-{container}"
    try:
        indexer = SearchIndexer(
            name=indexer_name,
            data_source_name=data_source_name,
            target_index_name=index_name,
            field_mappings=[
                FieldMapping(source_field_name="metadata_storage_name", target_field_name="metadata_storage_name"),
                FieldMapping(source_field_name="metadata_storage_path", target_field_name="metadata_storage_path"),
                FieldMapping(source_field_name="docid", target_field_name="docid"),
                FieldMapping(source_field_name="content", target_field_name="content"),
            ]
        )
        indexer_client.create_indexer(indexer)
        print(f"Created indexer: {indexer_name}")
    except ResourceExistsError:
        print(f"Indexer {indexer_name} already exists.")

    indexer_client.run_indexer(indexer_name)
    print(f"Started indexing for: {indexer_name}")

print("Created indices and started indexing for all containers.")

