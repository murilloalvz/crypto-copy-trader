from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.request import urlopen

YELLOWSTONE_COMMIT = "1bf1377f8ffd6919d3579b597b33ad980a214a7f"
PROTO_BASE = (
    "https://raw.githubusercontent.com/rpcpool/yellowstone-grpc/"
    f"{YELLOWSTONE_COMMIT}/yellowstone-grpc-proto/proto"
)
PROTO_FILES = ("geyser.proto", "solana-storage.proto")


def _download_if_missing(proto_dir: Path, name: str) -> None:
    path = proto_dir / name
    if path.exists():
        return
    url = f"{PROTO_BASE}/{name}"
    with urlopen(url, timeout=30) as response:
        payload = response.read()
    path.write_bytes(payload)


def main() -> int:
    try:
        import grpc_tools
        from grpc_tools import protoc
    except ImportError:
        print(
            "grpcio-tools is required. Run: "
            "python -m pip install -r benchmarks/yellowstone_raw_stream_v2/requirements.txt",
            file=sys.stderr,
        )
        return 2

    root = Path(__file__).resolve().parent
    proto_dir = root / "proto"
    generated_dir = root / "generated"
    proto_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "__init__.py").write_text("", encoding="utf-8")

    for name in PROTO_FILES:
        _download_if_missing(proto_dir, name)

    google_proto = Path(grpc_tools.__file__).resolve().parent / "_proto"
    args = [
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"-I{google_proto}",
        f"--python_out={generated_dir}",
        f"--grpc_python_out={generated_dir}",
        str(proto_dir / "geyser.proto"),
        str(proto_dir / "solana-storage.proto"),
    ]
    code = protoc.main(args)
    if code != 0:
        return code

    replacements = {
        generated_dir / "geyser_pb2.py": [
            (
                r"^import solana_storage_pb2 as solana__storage__pb2$",
                "from . import solana_storage_pb2 as solana__storage__pb2",
            ),
            (
                r"^from solana_storage_pb2 import \*$",
                "from .solana_storage_pb2 import *",
            ),
        ],
        generated_dir / "geyser_pb2_grpc.py": [
            (
                r"^import geyser_pb2 as geyser__pb2$",
                "from . import geyser_pb2 as geyser__pb2",
            )
        ],
    }

    for path, rules in replacements.items():
        text = path.read_text(encoding="utf-8")
        for pattern, replacement in rules:
            text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
        path.write_text(text, encoding="utf-8", newline="\n")

    print(
        f"Generated Yellowstone stubs in {generated_dir} "
        f"from rpcpool/yellowstone-grpc@{YELLOWSTONE_COMMIT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
