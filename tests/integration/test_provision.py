"""Provision two consumers against the pinned MinIO image."""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import boto3
import pytest
import yaml
from botocore.client import Config
from botocore.exceptions import ClientError

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "keystone-service.yaml"
MC_RELEASE = "RELEASE.2025-08-13T08-35-41Z"


@dataclass
class Stack:
    network: str
    container: str
    root_env: Path
    root_user: str
    root_password: str
    port: int
    server_image: str
    mc_image: str
    out_dir: Path


def _images() -> tuple[str, str]:
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return document["containers"]["server"]["image"], document["provision"]["image"]


def _image_present(ref: str) -> bool:
    return (
        subprocess.run(
            ["docker", "image", "inspect", ref],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _pull(ref: str) -> bool:
    if _image_present(ref):
        return True
    return subprocess.run(["docker", "pull", ref], capture_output=True, check=False).returncode == 0


def _write_env(path: Path, values: dict[str, str]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
    os.chmod(path, 0o600)


def _secret_absent(haystack: str, needle: str) -> None:
    if needle and needle in haystack:
        raise AssertionError("a secret appeared in command output")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Stack:
    server_image, mc_image = _images()
    if not _pull(server_image):
        pytest.skip("pinned MinIO server image is not available")
    if not _pull(mc_image):
        # The published mc image is the same RELEASE this server image already contains.
        probe = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "mc", server_image, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if MC_RELEASE not in probe.stdout:
            pytest.skip("pinned mc image is not available")
        mc_image = server_image

    work = tmp_path_factory.mktemp("minio")
    token = f"{os.getpid()}"
    network = f"ks-pkg-p01-{token}"
    container = f"ks-pkg-p01-minio-{token}"
    root_user = "ksroot"
    root_password = os.urandom(16).hex()
    root_env = work / "root.env"
    _write_env(
        root_env,
        {"MINIO_ROOT_USER": root_user, "MINIO_ROOT_PASSWORD": root_password},
    )
    out_dir = work / "out"
    out_dir.mkdir(mode=0o700)
    os.chmod(out_dir, 0o700)

    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "--network",
            network,
            "-p",
            "127.0.0.1::9000",
            "--env-file",
            str(root_env),
            server_image,
            "server",
            "/data",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)
        pytest.fail("could not start MinIO")

    port_text = subprocess.run(
        ["docker", "port", container, "9000"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    port = int(port_text.strip().rsplit(":", 1)[-1])
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 1):
                break
        except OSError:
            time.sleep(1)
    else:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)
        pytest.fail("MinIO did not accept connections")

    built = Stack(
        network=network,
        container=container,
        root_env=root_env,
        root_user=root_user,
        root_password=root_password,
        port=port,
        server_image=server_image,
        mc_image=mc_image,
        out_dir=out_dir,
    )
    try:
        yield built
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)


def _provision(
    stack: Stack,
    consumer: str,
    *,
    env_file: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "run",
            "--rm",
            # Root in the image would own the mode-600 secret, which Linux CI cannot read.
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--network",
            stack.network,
            "--env-file",
            str(env_file or stack.root_env),
            "-e",
            "MC_CONFIG_DIR=/tmp/mc",
            "-v",
            f"{ROOT}:/pkg:ro",
            "-v",
            f"{stack.out_dir}:/out",
            "--entrypoint",
            "/bin/sh",
            stack.mc_image,
            "/pkg/provision.sh",
            "--consumer",
            consumer,
            "--endpoint",
            f"http://{stack.container}:9000",
            "--secret-file",
            f"/out/{consumer}.secret",
        ]
    )


def _read_secret(path: Path) -> str:
    return path.read_text(encoding="utf-8").splitlines()[0]


def _client(stack: Stack, consumer: str):
    return boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{stack.port}",
        aws_access_key_id=consumer,
        aws_secret_access_key=_read_secret(stack.out_dir / f"{consumer}.secret"),
        region_name="us-east-1",
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=20,
            retries={"max_attempts": 2},
        ),
    )


def _denied(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    code = str(error.get("Code", ""))
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"AccessDenied", "403"} or status == 403


@pytest.fixture(scope="module")
def consumers(stack: Stack) -> Stack:
    first = _provision(stack, "svc-a")
    second = _provision(stack, "svc-b")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    return stack


def test_two_consumers_are_isolated(consumers: Stack) -> None:
    stack = consumers
    client_a = _client(stack, "svc-a")
    client_a.put_object(Bucket="svc-a", Key="owned.txt", Body=b"owned")
    assert client_a.get_object(Bucket="svc-a", Key="owned.txt")["Body"].read() == b"owned"
    for call in (
        lambda: client_a.put_object(Bucket="svc-b", Key="x", Body=b"no"),
        lambda: client_a.get_object(Bucket="svc-b", Key="x"),
        lambda: client_a.head_bucket(Bucket="svc-b"),
        lambda: client_a.delete_object(Bucket="svc-b", Key="x"),
    ):
        with pytest.raises(ClientError) as raised:
            call()
        assert _denied(raised.value)
    try:
        names = {item["Name"] for item in client_a.list_buckets().get("Buckets", [])}
    except ClientError as exc:
        assert _denied(exc)
    else:
        # This MinIO release lists the caller's own bucket instead of AccessDenied.
        assert names == {"svc-a"}


def test_rerun_is_idempotent(consumers: Stack) -> None:
    stack = consumers
    secret_path = stack.out_dir / "svc-a.secret"
    before = secret_path.read_bytes()
    client = _client(stack, "svc-a")
    client.put_object(Bucket="svc-a", Key="kept.txt", Body=b"still-here")
    again = _provision(stack, "svc-a")
    assert again.returncode == 0, again.stderr
    payload = json.loads(again.stdout.strip())
    assert payload["interface"] == "s3/v1"
    assert payload["bucket"] == "svc-a"
    assert payload["access_key"] == "svc-a"
    assert payload["path_style"] is True
    assert payload["secret_key_file"] == "/out/svc-a.secret"
    assert "secret_key" not in payload
    assert secret_path.read_bytes() == before
    assert client.get_object(Bucket="svc-a", Key="kept.txt")["Body"].read() == b"still-here"


def test_consumer_can_set_lifecycle(consumers: Stack) -> None:
    stack = consumers
    client = _client(stack, "svc-a")
    client.put_bucket_lifecycle_configuration(
        Bucket="svc-a",
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "svc-a-uploads",
                    "Filter": {"Prefix": "uploads/"},
                    "Status": "Enabled",
                    "Expiration": {"Days": 1},
                }
            ]
        },
    )
    rules = client.get_bucket_lifecycle_configuration(Bucket="svc-a")["Rules"]
    match = next(rule for rule in rules if rule["ID"] == "svc-a-uploads")
    assert match["Filter"]["Prefix"] == "uploads/"
    assert match["Expiration"]["Days"] == 1


def test_presigned_put_and_get_work(consumers: Stack) -> None:
    stack = consumers
    client = _client(stack, "svc-a")
    put_url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": "svc-a", "Key": "pre.txt"},
        ExpiresIn=60,
    )
    request = urllib.request.Request(put_url, data=b"presigned-body", method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            assert response.status == 200
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"presigned PUT failed with HTTP {exc.code}") from None
    get_url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": "svc-a", "Key": "pre.txt"},
        ExpiresIn=60,
    )
    try:
        with urllib.request.urlopen(get_url, timeout=20) as response:
            assert response.status == 200
            assert response.read() == b"presigned-body"
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"presigned GET failed with HTTP {exc.code}") from None


def test_wrong_root_password_exits_3(stack: Stack, tmp_path: Path) -> None:
    wrong = os.urandom(16).hex()
    env_file = tmp_path / "wrong.env"
    _write_env(env_file, {"MINIO_ROOT_USER": stack.root_user, "MINIO_ROOT_PASSWORD": wrong})
    result = _provision(stack, "svc-c", env_file=env_file)
    assert result.returncode == 3
    assert "volume" in result.stderr
    _secret_absent(result.stdout + result.stderr, stack.root_password)
    _secret_absent(result.stdout + result.stderr, wrong)


def test_secret_not_in_container_logs(stack: Stack) -> None:
    result = _provision(stack, "svc-a")
    assert result.returncode == 0
    consumer_secret = _read_secret(stack.out_dir / "svc-a.secret")
    logs = subprocess.run(
        ["docker", "logs", stack.container],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr + logs.stdout + logs.stderr
    _secret_absent(combined, stack.root_password)
    _secret_absent(combined, consumer_secret)
    secret_path = stack.out_dir / "svc-a.secret"
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
