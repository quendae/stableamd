import json
import os
import struct
import sys


def emit(payload, exit_code):
    print(json.dumps(payload, separators=(",", ":")))
    raise SystemExit(exit_code)


def fail(path, file_size, reason, **extra):
    payload = {
        "valid": False,
        "path": path,
        "file_size": file_size,
        "reason": reason,
    }
    payload.update(extra)
    emit(payload, 1)


def main():
    if len(sys.argv) != 2:
        emit({"valid": False, "reason": "usage: validate_safetensors.py <file>"}, 2)

    path = os.path.abspath(sys.argv[1])
    try:
        file_size = os.path.getsize(path)
    except OSError as exc:
        emit({"valid": False, "path": path, "file_size": None, "reason": str(exc)}, 1)

    if file_size < 8:
        fail(path, file_size, "file is shorter than the 8-byte safetensors header length prefix")

    try:
        with open(path, "rb") as handle:
            prefix = handle.read(8)
            if len(prefix) != 8:
                fail(path, file_size, "could not read the safetensors header length prefix")

            header_length = struct.unpack("<Q", prefix)[0]
            data_start = 8 + header_length
            if header_length == 0:
                fail(path, file_size, "safetensors header length is zero")
            if data_start > file_size:
                fail(
                    path,
                    file_size,
                    "safetensors header extends past the end of the file",
                    header_length=header_length,
                    required_minimum_size=data_start,
                )

            header_bytes = handle.read(header_length)
            if len(header_bytes) != header_length:
                fail(path, file_size, "safetensors header is truncated", header_length=header_length)
    except OSError as exc:
        fail(path, file_size, f"could not read file: {exc}")

    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(path, file_size, f"invalid safetensors JSON header: {exc}", header_length=header_length)

    if not isinstance(header, dict):
        fail(path, file_size, "safetensors header root is not an object", header_length=header_length)

    tensor_count = 0
    maximum_data_end = 0
    maximum_tensor_name = None

    for name, descriptor in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(descriptor, dict):
            fail(path, file_size, f"tensor descriptor for {name!r} is not an object")

        data_offsets = descriptor.get("data_offsets")
        if (
            not isinstance(data_offsets, list)
            or len(data_offsets) != 2
            or not all(isinstance(value, int) for value in data_offsets)
        ):
            fail(path, file_size, f"tensor {name!r} has invalid data_offsets")

        start, end = data_offsets
        if start < 0 or end < start:
            fail(path, file_size, f"tensor {name!r} has invalid data_offsets {data_offsets}")

        absolute_end = data_start + end
        if absolute_end > file_size:
            fail(
                path,
                file_size,
                f"tensor {name!r} extends past the end of the file",
                tensor=name,
                data_offsets=data_offsets,
                data_start=data_start,
                required_minimum_size=absolute_end,
                missing_bytes=absolute_end - file_size,
            )

        tensor_count += 1
        if end > maximum_data_end:
            maximum_data_end = end
            maximum_tensor_name = name

    if tensor_count == 0:
        fail(path, file_size, "safetensors header contains no tensors", header_length=header_length)

    emit(
        {
            "valid": True,
            "path": path,
            "file_size": file_size,
            "header_length": header_length,
            "data_start": data_start,
            "tensor_count": tensor_count,
            "maximum_data_end": maximum_data_end,
            "maximum_tensor_name": maximum_tensor_name,
            "required_minimum_size": data_start + maximum_data_end,
        },
        0,
    )


if __name__ == "__main__":
    main()
