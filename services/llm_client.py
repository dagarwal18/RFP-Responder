from typing import Optional
from persistence.secrets_repo import SecretsRepo

_repo = None

def _get_repo():
    global _repo
    if _repo is None:
        _repo = SecretsRepo()
    return _repo

async def set_llm_api_key(provider: str, api_key: str):
    """
    Store provider API key securely.
    """
    repo = _get_repo()
    repo.set_key(provider, api_key)
    # attempt to configure SDKs immediately (best-effort)
    try:
        if provider.lower() == "openai":
            _configure_openai(api_key)
    except Exception:
        pass

async def get_llm_api_key(provider: str) -> Optional[str]:
    repo = _get_repo()
    return repo.get_key(provider)

def _configure_openai(api_key: str):
    """
    Best-effort OpenAI SDK configuration (if openai is installed).
    """
    try:
        import openai
        openai.api_key = api_key
    except Exception:
        # SDK may not be installed; caller can import and set if needed.
        pass
