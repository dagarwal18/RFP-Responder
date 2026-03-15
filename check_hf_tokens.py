import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import requests
from rfp_automation.config import get_settings

def check_tokens():
    try:
        settings = get_settings()
    except Exception as e:
        print(f"Error loading settings: {e}")
        return

    keys_str = getattr(settings, "huggingface_api_keys", "")
    single_key = getattr(settings, "huggingface_api_key", "")
    
    keys = []
    if keys_str:
        keys.extend([k.strip() for k in keys_str.split(",") if k.strip()])
    if single_key and single_key.strip():
        keys.append(single_key.strip())
        
    # Deduplicate while preserving order
    keys = list(dict.fromkeys(keys))
    
    if not keys:
        print("No HuggingFace tokens found in config.")
        return
        
    print(f"Found {len(keys)} HuggingFace tokens to check.\n")
    
    for i, token in enumerate(keys):
        masked_token = f"{token[:5]}...{token[-5:]}" if len(token) > 10 else "***"
        print(f"[{i+1}/{len(keys)}] Checking token {masked_token}:")
        
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get("https://huggingface.co/api/whoami-v2", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                auth_data = data.get("auth", {}).get("accessToken", {})
                role = auth_data.get("role")
                name = data.get("name", "unknown")
                
                # Check write access
                fine_grained = auth_data.get("fineGrained", {})
                
                is_write = False
                if role in ["write", "admin"]:
                    is_write = True
                
                status = "VALID"
                access = "WRITE" if is_write else f"READ (Role={role}, FineGrained={bool(fine_grained)})"
                
                print(f"  -> Status: {status}")
                print(f"  -> Access: {access}")
                print(f"  -> User/Org: {name}")
            else:
                print(f"  -> Status: INVALID (HTTP {resp.status_code})")
                try:
                    error_msg = resp.json().get('error')
                    if error_msg:
                        print(f"  -> Error: {error_msg}")
                except Exception:
                    pass
        except Exception as e:
            print(f"  -> Request failed: {e}")
        print("-" * 50)

if __name__ == "__main__":
    check_tokens()
