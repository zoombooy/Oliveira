"""本地对象存储适配器。

领域层只保存相对 object_key。后续切换 S3/MinIO 时替换 adapter，不改变文档
版本和证据模型。
"""

from pathlib import Path

from app.core.config import get_settings


class LocalObjectStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or get_settings().data_dir)

    def put_bytes(self, key: str, data: bytes) -> str:
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("object_key 必须是 data_dir 下的相对路径")
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative.as_posix()

    def get_bytes(self, key: str) -> bytes:
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("object_key 必须是 data_dir 下的相对路径")
        return (self.root / relative).read_bytes()
