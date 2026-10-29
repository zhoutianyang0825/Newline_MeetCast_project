"""上传文件校验与落盘（素材本体存储；生产版换 OSS/CDN，url 前缀在 settings.PUBLIC_BASE）

常量全部来自 app/settings.py，这里只放"动作"。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import UploadFile

from app.errors import ApiError, CODE_FILE_TOO_LARGE, CODE_FORMAT_UNSUPPORTED
from app.settings import ACCEPTED_FORMATS, CHUNK_BYTES, MAX_FILE_BYTES, UPLOAD_DIR


def extension_of(filename: str) -> str:
    """取文件名后缀（小写，不带点）。

    得到的数据：
        filename（客户端上传的文件名，如 "Q3-review-cover.PNG"）。

    要做的操作：
        用 pathlib 取 suffix，去点转小写。

    返回：
        "png"；没有后缀返回 ""。

    为什么：格式校验和落盘命名都以后缀为准，统一在这里归一化。
    """
    return Path(filename).suffix.lstrip(".").lower()


def ensure_format(filename: str) -> str:
    """校验格式是否在白名单内。

    得到的数据：
        filename（上传文件名）。

    要做的操作：
        取后缀，不在 ACCEPTED_FORMATS 里就抛 2005。

    返回：
        "png"（合法后缀）。

    为什么：规范要求冷门格式明确拒绝（2005），不能静默失败让人以为传成功了。
    """
    ext = extension_of(filename)
    if ext not in ACCEPTED_FORMATS:
        raise ApiError(CODE_FORMAT_UNSUPPORTED, f"格式不支持：{ext or '无后缀'}，仅支持 {'/'.join(sorted(ACCEPTED_FORMATS))}")
    return ext


async def save_upload(file: UploadFile, material_id: str) -> tuple[str, float]:
    """把上传文件分块写到本地磁盘。

    得到的数据：
        file（FastAPI UploadFile，带 .filename 和异步 .read）；
        material_id（素材 id，如 "mat_003"，用来命名落盘文件）。

    要做的操作：
        校验后缀 → 建目录 → 分块读 1MB 写盘；
        累计字节超 500MB → 删掉半个文件并抛 2007。

    返回：
        (落盘路径, 文件大小 MB)，如 ("/.../data/uploads/mat_003.png", 2.4)

    为什么：500MB 整包读会把内存打满；超限必须回滚半成品文件，否则磁盘留垃圾。
    """
    ext = ensure_format(file.filename or "")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f"{material_id}.{ext}"

    written = 0
    with target.open("wb") as fp:
        while True:
            chunk = await file.read(CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_FILE_BYTES:
                fp.close()
                target.unlink(missing_ok=True)
                raise ApiError(CODE_FILE_TOO_LARGE)
            fp.write(chunk)

    size_mb = round(written / (1024 * 1024), 2)
    return str(target), size_mb


def remove_file(file_path: str) -> None:
    """删除本地素材文件（幂等）。

    得到的数据：
        file_path（落盘绝对路径，Material.file_path）。

    要做的操作：
        Path.unlink(missing_ok=True)，文件不在也不报错。

    返回：
        无。

    为什么：删素材要连文件一起删，重复删/文件已被清走都不该让接口失败。
    """
    if not file_path:
        return
    Path(file_path).unlink(missing_ok=True)


# 全量哈希上限：超过就改"首尾采样 + 文件大小"，避免设备预拉取清单接口被大文件拖死
FULL_HASH_MAX_BYTES = 32 * 1024 * 1024
SAMPLE_BYTES = 1024 * 1024


def ensure_seed_material_file(material_id: str = "mat_001") -> None:
    """给种子素材准备一份真实文件。

    得到的数据：
        material_id（种子素材 id，如 "mat_001"），默认对应 store.seed() 里那条公共素材。

    要做的操作：
        目标文件 data/uploads/<id>.png 已存在 → 直接返回；
        不存在 → 从项目 brand/logo_icon.png 复制一份过去。

    返回：
        无。

    为什么：种子素材若只有记录没有文件，设备预拉取会一直 404 重试，
             日志里全是"下载失败"，把真正的错误淹没掉。演示环境必须自洽。
    """
    target = UPLOAD_DIR / f"{material_id}.png"
    if target.exists():
        return
    brand_logo = Path(__file__).resolve().parent.parent.parent / "brand" / "logo_icon.png"
    if not brand_logo.is_file():
        return
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(brand_logo.read_bytes())


def quick_checksum(file_path: str) -> str | None:
    """算素材的完整性校验串（设备预拉取后比对，防止半截文件被当成素材）。

    得到的数据：
        file_path（落盘绝对路径，如 "/.../data/uploads/mat_003.mp4"）。

    要做的操作：
        文件不存在 → 返回 None（种子素材没有实体文件，属正常）；
        文件 ≤32MB → 全量 sha256；
        文件 >32MB → 首 1MB + 尾 1MB + 文件字节数 合成 sha256，前缀标 partial。

    返回：
        "sha256:9f3a..." ／ "sha256-partial:1b2c..." ／ None

    为什么：设备下载完必须能判断"文件是否完整"；500MB 视频做全量哈希每次列表都要读一遍盘，
            代价不可接受，采样哈希在工程上是够用的折中。
    """
    path = Path(file_path) if file_path else None
    if path is None or not path.is_file():
        return None

    size = path.stat().st_size
    digest = hashlib.sha256()
    if size <= FULL_HASH_MAX_BYTES:
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(CHUNK_BYTES), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    with path.open("rb") as fp:
        digest.update(fp.read(SAMPLE_BYTES))
        fp.seek(-SAMPLE_BYTES, 2)
        digest.update(fp.read(SAMPLE_BYTES))
    digest.update(str(size).encode())
    return f"sha256-partial:{digest.hexdigest()}"
