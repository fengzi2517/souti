"""upload.safe_upload_path 单测：路径穿越防护"""
import pytest
from fastapi import HTTPException

from app.routers.upload import safe_upload_path


@pytest.mark.parametrize("attack", [
    "../../backend/.env",
    "..\\..\\backend\\.env",
    "....//....//etc/passwd",
    "./../../etc/passwd",
    "sub/dir/file.png",
    "a b.png",
    "UPPER.PNG!",
    "a1b2c3d4.png",                     # 非 UUID 形态
    "F47AC10B-58CC-4372-A567-0E02B2C3D479.png",  # 大写
    "f47ac10b-58cc-4372-a567-0e02b2c3d479.gif",  # 非白名单后缀
    "f47ac10b-58cc-4372-a567-0e02b2c3d479.png.exe",
])
def test_traversal_and_bad_names_rejected(attack):
    with pytest.raises(HTTPException) as e:
        safe_upload_path(attack)
    assert e.value.status_code == 422


@pytest.mark.parametrize("ok", [
    "f47ac10b-58cc-4372-a567-0e02b2c3d479.png",
    "0e02b2c3-d479-4f47-ac10-b58cc4372a56.jpg",
])
def test_valid_uuid_names_pass(ok):
    p = safe_upload_path(ok)
    assert p.name == ok
