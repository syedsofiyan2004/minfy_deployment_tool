from pathlib import Path
import yaml
from pydantic import BaseModel, Field, ValidationError
HOME_DIR = Path('.') / '.minfy'
GLOBAL_CFG = HOME_DIR / "config.yaml"
HOME_DIR.mkdir(exist_ok=True)

class AWSAuth(BaseModel):
    access_key: str = Field(..., alias="aws_access_key_id")
    secret_key: str = Field(..., alias="aws_secret_access_key")
    session_token: str | None = Field(None, alias="aws_session_token")
    region: str = "ap-south-1"
    profile: str | None = None

def save_global(auth: AWSAuth):
    GLOBAL_CFG.write_text(
        yaml.safe_dump(auth.model_dump(by_alias=True)), encoding='utf-8'
    )
    try:
        GLOBAL_CFG.chmod(0o600)
    except (AttributeError, PermissionError):
        pass  

def load_global() -> AWSAuth | None:
    if not GLOBAL_CFG.exists():
        return None
    try:
        data = yaml.safe_load(GLOBAL_CFG.read_text())
        return AWSAuth(**data)
    except (ValidationError, yaml.YAMLError):
        raise RuntimeError("Corrupted ~/.minfy/config.yaml")
