"""Centralised configuration — all env vars read here once.

`settings()` returns a fresh immutable snapshot each call so tests/runtime that
mutate the environment see updated values. `.env` is loaded by `core.llm` at
import time (added in a later phase); for now we load it here too so the app
runs standalone.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")
load_dotenv()  

def env_str(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val is not None and val != "" else default

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, "1" if default else "0").strip().lower() in {
        "1", "true", "yes", "on",
    }

def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _real(value: str) -> bool:
    """True only for a genuinely-configured value (non-empty, not a placeholder).

    Guards against the .env.example placeholders ("your_token", "your-company...",
    "changeme", ...) accidentally enabling live connectors.
    """
    v = (value or "").strip().lower()
    if not v:
        return False
    return not any(tok in v for tok in ("your_", "your-", "changeme", "<", "example.com"))


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of runtime configuration."""

    # --- app ---
    app_env: str
    debug: bool
    port: int
    frontend_url: str

    # --- data directories ---
    inputs_dir: str
    outputs_dir: str
    processing_dir: str

    # --- Azure OpenAI  ---
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str
    azure_openai_deployment: str
    azure_openai_embedding_deployment: str

    # --- understanding agent ---
    understanding_batch: int
    understanding_max_llm_blocks: int

    # --- Azure Document Intelligence (optional frame OCR) ---
    docintel_endpoint: str
    docintel_key: str

    # --- transcription ---
    transcribe_backend: str  # "azure" | "local"
    local_whisper_model: str
    local_whisper_chunk_secs: int
    azure_media_chunk_secs: int
    azure_whisper_deployment: str

    # --- media / video tool ---
    media_max_frames: int
    caption_frames: bool
    ocr_frames: bool
    video_chunk_secs: float
    video_frame_interval: float
    video_similarity_threshold: float
    video_analyze_frames: bool

    # --- Jira connector ---
    jira_server_url: str
    jira_username: str
    jira_api_token: str
    jira_jql: str

    # --- SharePoint connector ---
    sp_tenant_id: str
    sp_client_id: str
    sp_client_secret: str
    sp_site_url: str
    sp_folder: str

    # --- storage backend ---
    storage_backend: str                  # "local" | "azure"
    local_data_dir: str
    azure_storage_account: str            # account name, e.g. "ckmstudio"
    azure_storage_sas_token: str          # account- or container-scoped SAS
    blob_endpoint: str                    # optional explicit blob endpoint override
    blob_container: str
    sas_ttl_minutes: int

    # --- state store ---
    state_backend: str                    # "local" | "azure" | "redis"
    table_endpoint: str                   # https://<acct>.table.core.windows.net
    table_sas_token: str                  # SAS for Table service (or reuse storage SAS)
    workspace_table: str
    session_table: str
    redis_url: str                        # redis://host:port/db (redis backend)
    redis_namespace: str                  # key prefix for all redis state keys

    # --- job queue (async builds) ---
    queue_backend: str                    # "local" | "azure"
    servicebus_connection_string: str
    servicebus_queue: str
    worker_max_wait_secs: int

 # --- retrieval (RAG index) ---
    retrieval_backend: str                # "local" | "azure"
    search_endpoint: str                  # https://<svc>.search.windows.net
    search_api_key: str                   # admin key (index + query)
    search_index: str
    search_vector_dim: int
    retrieval_top_k: int

    # --- auth (JWT) ---
    jwt_secret: str
    jwt_algorithm: str
    jwt_ttl_minutes: int

    @property
    def azure_openai_configured(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def cors_origins(self) -> list[str]:
        # comma-separated list supported; falls back to the single frontend URL
        raw = env_str("CORS_ORIGINS", self.frontend_url)
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def docintel_configured(self) -> bool:
        return bool(self.docintel_endpoint and self.docintel_key)

    @property
    def transcribe_azure(self) -> bool:
        return self.transcribe_backend == "azure" and self.azure_openai_configured

    @property
    def jira_configured(self) -> bool:
        return _real(self.jira_server_url) and _real(self.jira_username) and _real(self.jira_api_token)

    @property
    def sharepoint_configured(self) -> bool:
        return (_real(self.sp_tenant_id) and _real(self.sp_client_id)
                and _real(self.sp_client_secret) and _real(self.sp_site_url))

    @property
    def storage_azure(self) -> bool:
        return self.storage_backend == "azure"
    
    @property
    def state_azure(self) -> bool:
        return self.state_backend == "azure"

    @property
    def state_redis(self) -> bool:
        return self.state_backend == "redis"

    @property
    def queue_azure(self) -> bool:
        return self.queue_backend == "azure"

    @property
    def blob_account_url(self) -> str:
        if self.blob_endpoint:
            return self.blob_endpoint.rstrip("/")

        return f"https://{self.azure_storage_account}.blob.core.windows.net"
    

    @property
    def table_account_url(self) -> str:
        if self.table_endpoint:
            return self.table_endpoint.rstrip("/")
        return f"https://{self.azure_storage_account}.table.core.windows.net"

    @property
    def retrieval_azure(self) -> bool:
        return self.retrieval_backend == "azure"

    @property
    def search_configured(self) -> bool:
        return bool(self.search_endpoint and self.search_api_key)

def settings() -> Settings:
    return Settings(
        app_env=env_str("APP_ENV", "development"),
        debug=env_flag("DEBUG", True),
        port=env_int("PORT", 8000),
        frontend_url=env_str("FRONTEND_URL", "http://localhost:5173"),
        inputs_dir=env_str("INPUTS_DIR", str(BACKEND_ROOT / "data" / "inputs")),
        outputs_dir=env_str("OUTPUTS_DIR", str(BACKEND_ROOT / "data" / "outputs")),
        processing_dir=env_str("PROCESSING_DIR", str(BACKEND_ROOT / "data" / "processing")),
        azure_openai_endpoint=env_str("AZURE_OPENAI_ENDPOINT", ""),
        azure_openai_api_key=env_str("AZURE_OPENAI_API_KEY", ""),
        azure_openai_api_version=env_str("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        azure_openai_deployment=env_str("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        azure_openai_embedding_deployment=env_str("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""),
        understanding_batch=env_int("UNDERSTANDING_BATCH", 25),
        understanding_max_llm_blocks=env_int("UNDERSTANDING_MAX_LLM_BLOCKS", 300),
        docintel_endpoint=env_str("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", ""),
        docintel_key=env_str("AZURE_DOCUMENT_INTELLIGENCE_KEY", ""),
        transcribe_backend=env_str("MEDIA_TRANSCRIBE_BACKEND", "azure").strip().lower(),
        local_whisper_model=env_str("LOCAL_WHISPER_MODEL", "base"),
        local_whisper_chunk_secs=env_int("LOCAL_WHISPER_CHUNK_SECS", 30),
        azure_media_chunk_secs=env_int("AZURE_MEDIA_CHUNK_SECS", 600),
        azure_whisper_deployment=env_str("AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper"),
        media_max_frames=env_int("MEDIA_MAX_FRAMES", 60),
        caption_frames=env_flag("AZURE_MEDIA_CAPTION_FRAMES", True),
        ocr_frames=env_flag("AZURE_MEDIA_OCR_FRAMES", False),
        video_chunk_secs=env_float("VIDEO_CHUNK_SECS", 90.0),
        video_frame_interval=env_float("VIDEO_FRAME_INTERVAL", 5.0),
        video_similarity_threshold=env_float("VIDEO_SIMILARITY_THRESHOLD", 0.95),
        video_analyze_frames=env_flag("VIDEO_ANALYZE_FRAMES", True),
        jira_server_url=env_str("JIRA_SERVER_URL", ""),
        jira_username=env_str("JIRA_USERNAME", ""),
        jira_api_token=env_str("JIRA_API_TOKEN", ""),
        jira_jql=env_str("JIRA_JQL", ""),
        sp_tenant_id=env_str("SHAREPOINT_TENANT_ID", ""),
        sp_client_id=env_str("SHAREPOINT_CLIENT_ID", ""),
        sp_client_secret=env_str("SHAREPOINT_CLIENT_SECRET", ""),
        sp_site_url=env_str("SHAREPOINT_SITE_URL", ""),
        sp_folder=env_str("SHAREPOINT_FOLDER", "Shared Documents"),
        storage_backend=env_str("STORAGE_BACKEND", "local").strip().lower(),
        local_data_dir=env_str("LOCAL_DATA_DIR", str(BACKEND_ROOT / "data" / "workspaces")),
        azure_storage_account=env_str("AZURE_STORAGE_ACCOUNT_NAME", ""),
        azure_storage_sas_token=env_str("AZURE_STORAGE_SAS_TOKEN", ""),
        blob_endpoint=env_str("AZURE_BLOB_ENDPOINT", ""),
        blob_container=env_str("AZURE_BLOB_CONTAINER_NAME", "cstt-workspaces"),
        sas_ttl_minutes=env_int("SAS_TTL_MINUTES", 60),
        state_backend=env_str("STATE_BACKEND", env_str("STORAGE_BACKEND", "local")).strip().lower(),
        table_endpoint=env_str("AZURE_TABLE_ENDPOINT", ""),
        table_sas_token=env_str("AZURE_TABLE_SAS_TOKEN", env_str("AZURE_STORAGE_SAS_TOKEN", "")),
        workspace_table=env_str("AZURE_WORKSPACE_TABLE", "workspaces"),
        session_table=env_str("AZURE_SESSION_TABLE", "sessions"),
        redis_url=env_str("REDIS_URL", ""),
        redis_namespace=env_str("REDIS_NAMESPACE", "cstt"),
        queue_backend=env_str("QUEUE_BACKEND", env_str("STORAGE_BACKEND", "local")).strip().lower(),
        servicebus_connection_string=env_str("AZURE_SERVICEBUS_CONNECTION_STRING", ""),
        servicebus_queue=env_str("AZURE_SERVICEBUS_QUEUE_NAME", "cstt-builds"),
        worker_max_wait_secs=env_int("WORKER_MAX_WAIT_SECS", 30),
        retrieval_backend=env_str("RETRIEVAL_BACKEND", env_str("STORAGE_BACKEND", "local")).strip().lower(),
        search_endpoint=env_str("AZURE_SEARCH_ENDPOINT", ""),
        search_api_key=env_str("AZURE_SEARCH_API_KEY", ""),
        search_index=env_str("AZURE_SEARCH_INDEX_NAME", "cstt-blocks"),
        search_vector_dim=env_int("AZURE_SEARCH_VECTOR_DIM", 1536),
        retrieval_top_k=env_int("RETRIEVAL_TOP_K", 8),
        jwt_secret=env_str("JWT_SECRET", "dev-insecure-change-me"),
        jwt_algorithm=env_str("JWT_ALGORITHM", "HS256"),
        jwt_ttl_minutes=env_int("JWT_TTL_MINUTES", 60 * 24),
    )