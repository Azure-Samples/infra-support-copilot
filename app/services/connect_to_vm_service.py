"""
RAG Chat Service using Azure OpenAI and AI Search
"""
import logging
import paramiko
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
from app.config import settings


logger = logging.getLogger(__name__)

class ConnectToVMService:
    """
    Service that provides RAG capabilities by connecting Azure OpenAI with Azure AI Search.
    """
    
    def __init__(self):
        # Store settings
        self.openai_endpoint = settings.azure_openai_endpoint
        self.gpt_deployment = settings.azure_openai_gpt_deployment
        self.azure_openai_api_version = settings.azure_openai_api_version

        self.vm_admin_username = settings.vm_admin_username
        self.vm_name = settings.vm_name 
        self.vm_public_ip = settings.vm_public_ip
        self.vm_fqdn = settings.vm_fqdn
        self.virtual_network_name = settings.virtual_network_name

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

        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    async def _connect_to_vm(self, password: str, user_query: str):
        try:
            _execute_command = await self.openai_client.chat.completions.create(
                model=self.gpt_deployment,
                messages=[
                    {
                        "role": "system", 
                        "content": f"Please output the Linux command.\n\
                            Only output the command without any explanation.\n\
                            Example: dpkg --list"
                    },
                    {"role": "user", "content": user_query}
                ]
            )

            execute_command = _execute_command.choices[0].message.content.strip()

            self.ssh_client.connect(hostname=self.vm_public_ip, username=self.vm_admin_username, password=password)
            _, stdout, _ = self.ssh_client.exec_command(execute_command)
            output = []
            for line in stdout:
                output.append(line.strip())
            return output
        except paramiko.AuthenticationException:
            logger.error("認証に失敗しました。ユーザー名とパスワードを確認してください。")
            return None
        except paramiko.SSHException as ssh_exception:
            logger.error(f"SSH接続エラー: {ssh_exception}")
            return None


    def _parse_dpkg_output(self, dpkg_lines):
        """dpkgの出力をマークダウン表形式に変換"""
        if not dpkg_lines:
            return "パッケージ情報がありません。"
        
        package_lines = []
        for line in dpkg_lines:
            if line and len(line) > 4 and line[0:2] in ['ii', 'rc', 'un', 'pn']:
                package_lines.append(line)
        
        if not package_lines:
            return "インストール済みパッケージが見つかりませんでした。"
        
        markdown_table = "| Status | Package Name | Version | Architecture | Description |\n"
        markdown_table += "|--------|--------------|---------|--------------|-------------|\n"
        
        for line in package_lines:
            parts = line.split(None, 4) 
            if len(parts) >= 4:
                status = parts[0]
                package_name = parts[1]
                version = parts[2]
                architecture = parts[3]
                description = parts[4] if len(parts) > 4 else ""
                
                markdown_table += f"| {status} | {package_name} | {version} | {architecture} | {description} |\n"
        
        return markdown_table

    async def get_chat_completion(self, effective_query: str):
        try:
            if effective_query.upper().startswith(";;VM_PASSWORD;;"):
                [password_part, user_query] = effective_query.split("|||", 1)
                password = password_part.split(";;VM_PASSWORD;;", 1)[1]
                dpkg_list = await self._connect_to_vm(password, user_query)
                if dpkg_list:
                    markdown_table = self._parse_dpkg_output(dpkg_list)
                    
                    if len(markdown_table) > 8000:
                        lines = markdown_table.split('\n')
                        header_lines = lines[:2]  # ヘッダー2行
                        data_lines = lines[2:]
                        half_point = len(data_lines) // 2
                        truncated_lines = header_lines + data_lines[:half_point] + ["| ... | (truncated) | ... | ... | ... |"]
                        markdown_table = '\n'.join(truncated_lines)
                    
                    return [{"title": "VM Installed Packages (dpkg --list)", "content": f"## インストール済みパッケージ一覧:\n\n{markdown_table}\n"}]
                else:
                    return [{"title": "VM Connection Error", "content": "## Error:\nVMへの接続に失敗しました。パスワードを確認してください。\n"}]
        except Exception as e:
            if hasattr(e, 'status_code'):
                logger.error(f"Error in get_chat_completion (status {getattr(e, 'status_code', 'n/a')}): {e}")
            else:
                logger.error(f"Error in get_chat_completion: {e}")
            raise

connect_to_vm_service = ConnectToVMService()
