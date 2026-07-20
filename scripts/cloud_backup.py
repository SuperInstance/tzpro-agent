#!/usr/bin/env python3
"""
Cloud Backup Client for Vessel Data Twin

R2 S3-compatible multipart upload with 8MiB parts, per-vessel prefix,
manifest-LAST commit marker, content-addressed keys, resume via ListParts.

Stdlib only - no external dependencies. AWS Signature V4 implemented from scratch.

Environment Variables:
    R2_ACCOUNT_ID       - Cloudflare account ID
    R2_ACCESS_KEY_ID    - R2 access key ID
    R2_SECRET_ACCESS_KEY- R2 secret access key (never logged)
    R2_BUCKET           - R2 bucket name
    VESSEL_ID           - Vessel identifier for prefix scoping
    VESSEL_HMAC_KEY     - Hex-encoded HMAC key for manifest signing (32 bytes)

Usage:
    python cloud_backup.py --status
    python cloud_backup.py --day 2026-07-19
    python cloud_backup.py --verify 2026-07-19
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import hmac
import urllib.parse
import urllib.request
import urllib.error
import datetime
import time
import tarfile
import tempfile
import shutil
import threading
import http.server
import socketserver
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple, Callable
from dataclasses import dataclass, field


# ============================================================================
# Configuration and Constants
# ============================================================================

PART_SIZE_MB = 8
PART_SIZE_BYTES = PART_SIZE_MB * 1024 * 1024  # 8MiB as per R2 requirements
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds

# R2 endpoint format: https://<account_id>.r2.cloudflarestorage.com
R2_HOST_TEMPLATE = "{account_id}.r2.cloudflarestorage.com"

# Required environment variables
REQUIRED_ENV_VARS = [
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "VESSEL_ID",
]

OPTIONAL_ENV_VARS = ["VESSEL_HMAC_KEY"]


# ============================================================================
# Structured Logging
# ============================================================================

class StructuredLogger:
    """JSON-formatted logger for structured output."""

    def __init__(self, level: str = "INFO"):
        self.level = level
        self._lock = threading.Lock()

    def _log(self, level: str, message: str, **kwargs):
        if level != self.level and self._should_log(level):
            return
        with self._lock:
            log_entry = {
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "level": level,
                "message": message,
                **kwargs
            }
            print(json.dumps(log_entry), file=sys.stderr)

    def _should_log(self, level: str) -> bool:
        levels = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
        return levels.get(level, 1) >= levels.get(self.level, 1)

    def debug(self, message: str, **kwargs):
        self._log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log("INFO", message, **kwargs)

    def warn(self, message: str, **kwargs):
        self._log("WARN", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("ERROR", message, **kwargs)


logger = StructuredLogger()


# ============================================================================
# AWS Signature V4 Implementation (Stdlib Only)
# ============================================================================

class SigV4Signer:
    """
    AWS Signature Version 4 signer implementation from scratch.

    Reference: AWS Signature V4 signing process
    https://docs.aws.amazon.com/general/latest/gr/signature-version-4.html
    """

    ALGORITHM = "AWS4-HMAC-SHA256"
    SERVICE = "s3"

    def __init__(self, access_key_id: str, secret_access_key: str, region: str = "auto"):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.region = region

    def _get_signing_key(self, date_stamp: str) -> bytes:
        """Derive the signing key from date and secret."""
        # kDate = HMAC("AWS4" + SecretAccessKey, Date)
        k_date = self._hmac_sha256(
            ("AWS4" + self.secret_access_key).encode("utf-8"),
            date_stamp.encode("utf-8")
        )
        # kRegion = HMAC(kDate, Region)
        k_region = self._hmac_sha256(k_date, self.region.encode("utf-8"))
        # kService = HMAC(kRegion, Service)
        k_service = self._hmac_sha256(k_region, self.SERVICE.encode("utf-8"))
        # kSigning = HMAC(kService, "aws4_request")
        k_signing = self._hmac_sha256(k_service, b"aws4_request")
        return k_signing

    @staticmethod
    def _hmac_sha256(key: bytes, data: bytes) -> bytes:
        """HMAC-SHA256 using stdlib."""
        return hmac.new(key, data, hashlib.sha256).digest()

    @staticmethod
    def _sha256(data: bytes) -> bytes:
        """SHA256 hash using stdlib."""
        return hashlib.sha256(data).digest()

    @staticmethod
    def _hash_hex(data: bytes) -> str:
        """SHA256 hash as hex string."""
        return hashlib.sha256(data).hexdigest()

    def _get_canonical_query_string(self, params: Dict[str, str]) -> str:
        """
        Create canonical query string per AWS spec.

        Test vector from AWS docs:
        input: {"Action": "CreateUser", "Version": "2010-05-08"}
        output: "Action=CreateUser&Version=2010-05-08"
        """
        encoded_params = []
        for key in sorted(params.keys()):
            encoded_value = urllib.parse.quote(params[key], safe="-_.~")
            encoded_params.append(f"{key}={encoded_value}")
        return "&".join(encoded_params)

    def sign_request(
        self,
        method: str,
        host: str,
        path: str,
        query_params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Dict[str, str]:
        """
        Sign an HTTP request with AWS Signature V4.

        Returns a dict of headers including Authorization.
        """
        now = datetime.datetime.utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        # Default headers
        if headers is None:
            headers = {}
        headers.setdefault("Host", host)
        headers.setdefault("Content-Type", "application/octet-stream")
        headers.setdefault("X-Amz-Date", amz_date)
        headers.setdefault("X-Amz-Content-Sha256", self._hash_hex(body))

        # Canonical URI
        canonical_uri = urllib.parse.quote(path, safe="/")

        # Canonical query string
        if query_params is None:
            query_params = {}
        canonical_querystring = self._get_canonical_query_string(query_params)

        # Canonical headers (signed headers list)
        signed_headers_list = sorted(
            [k.lower() for k in headers.keys() if k.lower() not in ["authorization"]]
        )
        signed_headers = ";".join(signed_headers_list)

        canonical_headers = []
        for k in signed_headers_list:
            header_value = headers.get(k, headers.get(k.capitalize(), ""))
            canonical_headers.append(f"{k.lower()}:{header_value.strip()}")
        canonical_headers_str = "\n".join(canonical_headers) + "\n"

        # Create payload hash
        payload_hash = self._hash_hex(body)

        # Canonical request
        canonical_request = "\n".join([
            method,
            canonical_uri,
            canonical_querystring,
            canonical_headers_str,
            signed_headers,
            payload_hash
        ])

        # Create string to sign
        credential_scope = f"{date_stamp}/{self.region}/{self.SERVICE}/aws4_request"
        string_to_sign = "\n".join([
            self.ALGORITHM,
            amz_date,
            credential_scope,
            self._hash_hex(canonical_request.encode("utf-8"))
        ])

        # Calculate signature
        signing_key = self._get_signing_key(date_stamp)
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        # Create authorization header
        authorization_header = (
            f"{self.ALGORITHM} "
            f"Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        result = headers.copy()
        result["Authorization"] = authorization_header

        return result


# ============================================================================
# R2 Client
# ============================================================================

class R2Client:
    """R2 S3-compatible client with multipart upload support."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        vessel_id: str,
    ):
        self.account_id = account_id
        self.bucket = bucket
        self.vessel_id = vessel_id
        self.host = R2_HOST_TEMPLATE.format(account_id=account_id)
        self.signer = SigV4Signer(access_key_id, secret_access_key, region="auto")
        self.prefix = f"vessels/{vessel_id}/"

    def _make_request(
        self,
        method: str,
        path: str,
        query_params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Make an HTTP request with SigV4 signing and retry logic."""
        url = f"https://{self.host}{path}"

        # Sign request
        signed_headers = self.signer.sign_request(
            method=method,
            host=self.host,
            path=path,
            query_params=query_params,
            headers=headers,
            body=body,
        )

        # Build urllib request
        if query_params:
            query_string = "&".join(
                f"{k}={urllib.parse.quote(v, safe='')}"
                for k, v in sorted(query_params.items())
            )
            url = f"{url}?{query_string}"

        req = urllib.request.Request(url, data=body, method=method)
        for k, v in signed_headers.items():
            req.add_header(k, v)

        # Execute with retry
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    f"Request attempt {attempt + 1}",
                    method=method,
                    path=path,
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    status = response.status
                    headers_dict = dict(response.headers)
                    body_bytes = response.read()
                    return status, headers_dict, body_bytes
            except urllib.error.HTTPError as e:
                # For HTTP errors, still return the response
                status = e.code
                headers_dict = dict(e.headers)
                body_bytes = e.read() if e.fp else b""
                if status < 500:  # Don't retry client errors
                    return status, headers_dict, body_bytes
                last_error = e
            except (urllib.error.URLError, OSError) as e:
                last_error = e

            # Backoff before retry
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.debug(f"Retry backoff: {wait_time}s")
                time.sleep(wait_time)

        # Exhausted retries
        logger.error("Request failed after retries", error=str(last_error))
        raise last_error or Exception("Request failed")

    # ---------- Object Operations ----------

    def head_object(self, key: str) -> Optional[Dict[str, str]]:
        """Check if object exists via HEAD request."""
        path = f"/{self.bucket}/{self.prefix}{key}"
        status, headers, _ = self._make_request("HEAD", path)

        if status == 200:
            return headers
        elif status == 404:
            return None
        else:
            raise Exception(f"HEAD failed with status {status}")

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> bool:
        """Upload a single object."""
        path = f"/{self.bucket}/{self.prefix}{key}"
        headers = {"Content-Type": content_type}
        status, _, _ = self._make_request("PUT", path, headers=headers, body=data)
        return status == 200

    def get_object(self, key: str) -> Optional[bytes]:
        """Download a single object."""
        path = f"/{self.bucket}/{self.prefix}{key}"
        status, _, body = self._make_request("GET", path)
        if status == 200:
            return body
        elif status == 404:
            return None
        else:
            raise Exception(f"GET failed with status {status}")

    # ---------- Bucket Operations ----------

    def head_bucket(self) -> bool:
        """Verify bucket access and credentials."""
        path = f"/{self.bucket}/"
        status, _, _ = self._make_request("HEAD", path)
        return status == 200

    def list_objects(self, prefix: str, max_keys: int = 1000) -> List[Dict[str, Any]]:
        """List objects with a given prefix."""
        path = f"/{self.bucket}/"
        query_params = {
            "list-type": "2",
            "prefix": self.prefix + prefix,
            "max-keys": str(max_keys),
        }
        status, _, body = self._make_request("GET", path, query_params=query_params)

        if status != 200:
            return []

        # Parse ListObjectsV2 response
        try:
            result = json.loads(body.decode("utf-8"))
            return result.get("Contents", [])
        except json.JSONDecodeError:
            return []

    # ---------- Multipart Upload Operations ----------

    def create_multipart_upload(
        self,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Initiate multipart upload.

        Returns the upload ID for subsequent part uploads.
        """
        path = f"/{self.bucket}/{self.prefix}{key}"
        query_params = {"uploads": ""}
        headers = {"Content-Type": content_type}

        status, _, body = self._make_request(
            "POST", path, query_params=query_params, headers=headers
        )

        if status != 200:
            raise Exception(f"CreateMultipartUpload failed with status {status}")

        # Parse XML response for UploadId
        # Expected: <InitiateMultipartUploadResult><UploadId>...</UploadId></...>
        try:
            body_str = body.decode("utf-8")
            # Simple XML parse - find UploadId tag
            if "<UploadId>" in body_str:
                start = body_str.index("<UploadId>") + len("<UploadId>")
                end = body_str.index("</UploadId>", start)
                return body_str[start:end]
        except Exception as e:
            logger.error("Failed to parse UploadId", error=str(e))

        raise Exception("Could not extract UploadId from response")

    def upload_part(
        self,
        key: str,
        upload_id: str,
        part_number: int,
        data: bytes,
    ) -> Optional[str]:
        """
        Upload a single part.

        Returns the ETag of the uploaded part.
        """
        path = f"/{self.bucket}/{self.prefix}{key}"
        query_params = {
            "partNumber": str(part_number),
            "uploadId": upload_id,
        }

        status, headers, _ = self._make_request("PUT", path, query_params=query_params, body=data)

        if status == 200:
            return headers.get("ETag", "").strip('"')
        return None

    def list_parts(
        self,
        key: str,
        upload_id: str,
    ) -> List[Dict[str, Any]]:
        """
        List uploaded parts for resumability.

        Returns list of {PartNumber, ETag, Size} dicts.
        """
        path = f"/{self.bucket}/{self.prefix}{key}"
        query_params = {
            "uploadId": upload_id,
        }

        status, _, body = self._make_request("GET", path, query_params=query_params)

        if status != 200:
            return []

        # Parse ListParts response (XML)
        try:
            body_str = body.decode("utf-8")
            parts = []
            # Extract PartNumber and ETag from XML
            # Format: <Part><PartNumber>N</PartNumber><ETag>"..."</ETag><Size>...</Size></Part>
            in_part = False
            current_part = {}
            for line in body_str.split("\n"):
                line = line.strip()
                if "<Part>" in line:
                    in_part = True
                    current_part = {}
                elif "</Part>" in line:
                    in_part = False
                    if current_part:
                        parts.append(current_part)
                elif in_part:
                    if "<PartNumber>" in line:
                        start = line.index("<PartNumber>") + len("<PartNumber>")
                        end = line.index("</PartNumber>", start)
                        current_part["PartNumber"] = int(line[start:end])
                    elif "<ETag>" in line:
                        start = line.index("<ETag>") + len("<ETag>")
                        end = line.index("</ETag>", start)
                        current_part["ETag"] = line[start:end].strip('"')
                    elif "<Size>" in line:
                        start = line.index("<Size>") + len("<Size>")
                        end = line.index("</Size>", start)
                        current_part["Size"] = int(line[start:end])
            return parts
        except Exception as e:
            logger.error("Failed to parse ListParts response", error=str(e))
            return []

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: List[Dict[str, Any]],
    ) -> bool:
        """
        Complete multipart upload with part list.

        Parts format: [{"PartNumber": int, "ETag": str}, ...]
        """
        path = f"/{self.bucket}/{self.prefix}{key}"
        query_params = {"uploadId": upload_id}

        # Build XML body
        xml_parts = []
        for part in sorted(parts, key=lambda p: p["PartNumber"]):
            xml_parts.append(
                f'<Part><PartNumber>{part["PartNumber"]}</PartNumber>'
                f'<ETag>"{part["ETag"]}"</ETag></Part>'
            )
        xml_body = f"<CompleteMultipartUpload>{''.join(xml_parts)}</CompleteMultipartUpload>"

        status, _, _ = self._make_request(
            "POST",
            path,
            query_params=query_params,
            headers={"Content-Type": "application/xml"},
            body=xml_body.encode("utf-8"),
        )

        return status == 200

    def abort_multipart_upload(self, key: str, upload_id: str) -> bool:
        """Abort a multipart upload."""
        path = f"/{self.bucket}/{self.prefix}{key}"
        query_params = {"uploadId": upload_id}

        status, _, _ = self._make_request("DELETE", path, query_params=query_params)

        return status == 204


# ============================================================================
# Multipart Upload Manager
# ============================================================================

class MultipartUploadManager:
    """
    Manager for resumable multipart uploads with 8MiB parts.
    """

    def __init__(self, client: R2Client, key: str):
        self.client = client
        self.key = key
        self.upload_id: Optional[str] = None
        self.uploaded_parts: Dict[int, str] = {}  # part_number -> etag

    def start(self, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Initiate multipart upload and upload all parts."""
        total_size = len(data)
        num_parts = (total_size + PART_SIZE_BYTES - 1) // PART_SIZE_BYTES

        logger.info(
            f"Starting multipart upload",
            key=self.key,
            size_bytes=total_size,
            parts=num_parts,
        )

        # Create multipart upload
        self.upload_id = self.client.create_multipart_upload(self.key, content_type)

        # Upload each part with resume capability
        for part_num in range(1, num_parts + 1):
            offset = (part_num - 1) * PART_SIZE_BYTES
            part_data = data[offset:offset + PART_SIZE_BYTES]

            # Check if part already uploaded (resume)
            if part_num in self.uploaded_parts:
                logger.debug(f"Part {part_num} already uploaded, skipping")
                continue

            # Upload part with retry
            etag = None
            for attempt in range(MAX_RETRIES):
                try:
                    etag = self.client.upload_part(
                        self.key,
                        self.upload_id,
                        part_num,
                        part_data,
                    )
                    if etag:
                        self.uploaded_parts[part_num] = etag
                        logger.debug(
                            f"Uploaded part {part_num}/{num_parts}",
                            part_size=len(part_data),
                        )
                        break
                except Exception as e:
                    logger.warn(
                        f"Part upload attempt {attempt + 1} failed",
                        part=part_num,
                        error=str(e),
                    )
                    if attempt == MAX_RETRIES - 1:
                        # Try to resume by listing existing parts
                        self._resume()
                        raise

            if not etag:
                raise Exception(f"Failed to upload part {part_num}")

    def _resume(self) -> None:
        """List parts and update uploaded_parts for resume."""
        if not self.upload_id:
            return

        logger.info("Attempting to resume multipart upload...")
        parts = self.client.list_parts(self.key, self.upload_id)

        for part in parts:
            part_num = part.get("PartNumber")
            etag = part.get("ETag")
            if part_num and etag:
                self.uploaded_parts[part_num] = etag

        logger.info(f"Resuming with {len(self.uploaded_parts)} existing parts")

    def complete(self) -> bool:
        """Complete the multipart upload."""
        if not self.upload_id:
            raise Exception("Upload not started")

        parts_list = [
            {"PartNumber": pn, "ETag": etag}
            for pn, etag in sorted(self.uploaded_parts.items())
        ]

        logger.info(
            "Completing multipart upload",
            key=self.key,
            parts_count=len(parts_list),
        )

        return self.client.complete_multipart_upload(self.key, self.upload_id, parts_list)

    def abort(self) -> bool:
        """Abort the multipart upload."""
        if not self.upload_id:
            return True

        logger.warn("Aborting multipart upload", key=self.key)
        return self.client.abort_multipart_upload(self.key, self.upload_id)


# ============================================================================
# Manifest and Bundle Management
# ============================================================================

@dataclass
class ManifestEntry:
    """Single object entry in manifest."""
    key: str
    sha256: str
    size: int


@dataclass
class SessionManifest:
    """Session manifest for daily backup."""
    vessel_id: str
    session_id: str
    prev_manifest_hash: Optional[str]
    objects: List[ManifestEntry] = field(default_factory=list)
    cursor: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vessel_id": self.vessel_id,
            "session_id": self.session_id,
            "prev_manifest_hash": self.prev_manifest_hash,
            "objects": [
                {"key": o.key, "sha256": o.sha256, "size": o.size}
                for o in self.objects
            ],
            "cursor": self.cursor,
            "created_at": self.created_at,
        }


def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hash of data."""
    return hashlib.sha256(data).hexdigest()


def compute_manifest_hash(manifest: SessionManifest) -> str:
    """Compute hash of manifest for chain linking."""
    manifest_dict = manifest.to_dict()
    # Exclude prev_manifest_hash for chain linking
    manifest_dict_for_hash = {k: v for k, v in manifest_dict.items() if k != "prev_manifest_hash"}
    canonical = json.dumps(manifest_dict_for_hash, sort_keys=True)
    return compute_sha256(canonical.encode("utf-8"))


def sign_manifest_hmac(manifest: SessionManifest, hmac_key: bytes) -> str:
    """
    Sign manifest with HMAC-SHA256.

    Args:
        manifest: Session manifest to sign
        hmac_key: 32-byte HMAC key

    Returns:
        Hex-encoded signature
    """
    manifest_dict = manifest.to_dict()
    canonical = json.dumps(manifest_dict, sort_keys=True)
    signature = hmac.new(hmac_key, canonical.encode("utf-8"), hashlib.sha256)
    return signature.hexdigest()


def verify_manifest_hmac(manifest: SessionManifest, signature: str, hmac_key: bytes) -> bool:
    """Verify manifest HMAC signature."""
    expected = sign_manifest_hmac(manifest, hmac_key)
    return hmac.compare_digest(expected, signature)


def load_previous_manifest_hash(client: R2Client, day: str) -> Optional[str]:
    """Load the previous day's manifest hash for chain linking."""
    # Parse day to get previous day
    try:
        dt = datetime.datetime.strptime(day, "%Y-%m-%d")
        prev_dt = dt - datetime.timedelta(days=1)
        prev_day = prev_dt.strftime("%Y-%m-%d")

        # Try to get previous manifest
        manifest_key = f"manifests/{prev_day}.manifest.json"
        data = client.get_object(manifest_key)

        if data:
            prev_manifest = json.loads(data.decode("utf-8"))
            # Compute hash of previous manifest
            manifest_obj = SessionManifest(
                vessel_id=prev_manifest["vessel_id"],
                session_id=prev_manifest["session_id"],
                prev_manifest_hash=prev_manifest.get("prev_manifest_hash"),
                objects=[
                    ManifestEntry(**o)
                    for o in prev_manifest.get("objects", [])
                ],
                cursor=prev_manifest.get("cursor"),
                created_at=prev_manifest.get("created_at", ""),
            )
            return compute_manifest_hash(manifest_obj)
    except Exception as e:
        logger.debug("No previous manifest found", error=str(e))

    return None


def generate_session_id() -> str:
    """Generate unique session ID."""
    return f"{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{os.urandom(4).hex()}"


# ============================================================================
# Bundle Creation
# ============================================================================

def create_day_bundle(
    data_dir: Path,
    day: str,
    vessel_id: str,
) -> Tuple[bytes, str]:
    """
    Create a tar.gz bundle for a day's data.

    Returns:
        (bundle_data, sha256_hash)
    """
    logger.info(f"Creating bundle for day: {day}")

    # Create temporary directory for bundle
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / f"{day}.tar.gz"

        with tarfile.open(bundle_path, "w:gz") as tar:
            # Add records.jsonl if exists (export from meta.db)
            records_path = data_dir / "memory" / "records" / f"{day}.jsonl"
            if records_path.exists():
                tar.add(records_path, arcname=f"{day}/records.jsonl")
                logger.info(f"Added records.jsonl to bundle")

            # Add blobs referenced by frames of the day
            frames_dir = data_dir / "memory" / "frames" / day
            if frames_dir.exists():
                for frame_path in frames_dir.glob("*.json"):
                    tar.add(frame_path, arcname=f"{day}/frames/{frame_path.name}")
                logger.info(f"Added {len(list(frames_dir.glob('*.json')))} frame files")

            # Add any blobs referenced
            blobs_dir = data_dir / "memory" / "blobs" / day
            if blobs_dir.exists():
                for blob_path in blobs_dir.iterdir():
                    if blob_path.is_file():
                        tar.add(blob_path, arcname=f"{day}/blobs/{blob_path.name}")
                logger.info(f"Added blobs to bundle")

        # Read bundle and compute hash
        with open(bundle_path, "rb") as f:
            bundle_data = f.read()

        bundle_hash = compute_sha256(bundle_data)

        logger.info(
            f"Bundle created",
            size_bytes=len(bundle_data),
            sha256=bundle_hash,
        )

        return bundle_data, bundle_hash


# ============================================================================
# CLI Commands
# ============================================================================

def cmd_status(client: R2Client) -> int:
    """Verify credentials and print quota-relevant counts."""
    logger.info("Checking R2 credentials and bucket access...")

    try:
        # Verify credentials via HeadBucket
        if not client.head_bucket():
            logger.error("Bucket access failed - check credentials and bucket name")
            return 1

        logger.info("✓ Credentials verified - bucket accessible")

        # Count objects in prefix
        bundles = client.list_objects("bundles/", max_keys=1000)
        manifests = client.list_objects("manifests/", max_keys=1000)

        print("\n=== Cloud Backup Status ===")
        print(f"Vessel ID: {client.vessel_id}")
        print(f"Bucket: {client.bucket}")
        print(f"\nObject counts:")
        print(f"  Bundles: {len(bundles)}")
        print(f"  Manifests: {len(manifests)}")
        print(f"\nR2 Quota Info:")
        print(f"  Free storage: 10 GB/month")
        print(f"  Free Class A (PUT/COPY/POST): 1M/month")
        print(f"  Free Class B (GET/SELECT): 10M/month")
        print(f"  Multipart part size: {PART_SIZE_MB} MiB")
        print()

        return 0

    except Exception as e:
        logger.error("Status check failed", error=str(e))
        return 1


def cmd_day(
    client: R2Client,
    day: str,
    data_dir: Path,
    hmac_key: Optional[bytes],
) -> int:
    """Bundle and upload a day's twin content."""
    logger.info(f"Processing day: {day}")

    try:
        # Parse day
        datetime.datetime.strptime(day, "%Y-%m-%d")

        # Generate session ID
        session_id = generate_session_id()

        # Load previous manifest hash
        prev_hash = load_previous_manifest_hash(client, day)
        logger.info(f"Previous manifest hash: {prev_hash or 'none (first backup)'}")

        # Create bundle
        bundle_data, bundle_hash = create_day_bundle(data_dir, day, client.vessel_id)

        # Generate content-addressed key
        # Format: vessels/<vid>/bundles/YYYY/MM/DD/<sha256>.tar.gz
        dt = datetime.datetime.strptime(day, "%Y-%m-%d")
        bundle_key = f"bundles/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{bundle_hash}.tar.gz"

        # Check if bundle already exists (idempotent)
        if client.head_object(bundle_key):
            logger.info(f"Bundle already exists, skipping upload: {bundle_key}")
        else:
            # Upload bundle via multipart
            uploader = MultipartUploadManager(client, bundle_key)
            try:
                uploader.start(bundle_data, content_type="application/gzip")
                uploader.complete()
                logger.info(f"✓ Bundle uploaded: {bundle_key}")
            except Exception as e:
                uploader.abort()
                logger.error("Bundle upload failed, aborting", error=str(e))
                return 1

        # Create manifest
        manifest = SessionManifest(
            vessel_id=client.vessel_id,
            session_id=session_id,
            prev_manifest_hash=prev_hash,
            objects=[
                ManifestEntry(
                    key=bundle_key,
                    sha256=bundle_hash,
                    size=len(bundle_data),
                )
            ],
        )

        manifest_key = f"manifests/{day}.manifest.json"
        manifest_json = json.dumps(manifest.to_dict(), sort_keys=True)

        # Upload manifest LAST (commit marker)
        if not client.head_object(manifest_key):
            if client.put_object(
                manifest_key,
                manifest_json.encode("utf-8"),
                content_type="application/json",
            ):
                logger.info(f"✓ Manifest uploaded: {manifest_key}")

                # Upload signature if HMAC key provided
                if hmac_key:
                    signature = sign_manifest_hmac(manifest, hmac_key)
                    sig_key = f"{manifest_key}.sig"
                    client.put_object(
                        sig_key,
                        signature.encode("utf-8"),
                        content_type="text/plain",
                    )
                    logger.info(f"✓ Signature uploaded: {sig_key}")
            else:
                logger.error("Failed to upload manifest")
                return 1
        else:
            logger.info("Manifest already exists, skipping")

        print(f"\n=== Backup Complete ===")
        print(f"Day: {day}")
        print(f"Session: {session_id}")
        print(f"Bundle: {bundle_key}")
        print(f"Bundle size: {len(bundle_data):,} bytes")
        print(f"Manifest: {manifest_key}")

        return 0

    except Exception as e:
        logger.error("Day backup failed", error=str(e), exc_info=True)
        return 1


def cmd_verify(client: R2Client, day: str) -> int:
    """Verify a day's backup: manifest chain and object presence."""
    logger.info(f"Verifying backup for day: {day}")

    try:
        manifest_key = f"manifests/{day}.manifest.json"
        manifest_data = client.get_object(manifest_key)

        if not manifest_data:
            logger.error("Manifest not found", key=manifest_key)
            return 1

        manifest = json.loads(manifest_data.decode("utf-8"))

        print(f"\n=== Verification Report for {day} ===")

        # Verify chain link
        prev_hash = manifest.get("prev_manifest_hash")
        if prev_hash:
            print(f"Previous manifest hash: {prev_hash}")

            # Try to verify against previous day's manifest
            try:
                dt = datetime.datetime.strptime(day, "%Y-%m-%d")
                prev_dt = dt - datetime.timedelta(days=1)
                prev_day = prev_dt.strftime("%Y-%m-%d")

                prev_manifest_key = f"manifests/{prev_day}.manifest.json"
                prev_data = client.get_object(prev_manifest_key)

                if prev_data:
                    prev_manifest = json.loads(prev_data.decode("utf-8"))
                    # Compute hash of previous manifest
                    manifest_obj = SessionManifest(
                        vessel_id=prev_manifest["vessel_id"],
                        session_id=prev_manifest["session_id"],
                        prev_manifest_hash=prev_manifest.get("prev_manifest_hash"),
                        objects=[
                            ManifestEntry(**o)
                            for o in prev_manifest.get("objects", [])
                        ],
                        cursor=prev_manifest.get("cursor"),
                        created_at=prev_manifest.get("created_at", ""),
                    )
                    computed_hash = compute_manifest_hash(manifest_obj)

                    if computed_hash == prev_hash:
                        print("✓ Chain link verified")
                    else:
                        print("✗ Chain link BROKEN")
                        print(f"  Expected: {prev_hash}")
                        print(f"  Computed: {computed_hash}")
                else:
                    print("⚠ Previous manifest not found for chain verification")
            except Exception as e:
                print(f"⚠ Chain verification error: {e}")
        else:
            print("No previous manifest (first backup in chain)")

        # Verify objects
        print(f"\nObjects: {len(manifest.get('objects', []))}")
        all_present = True
        for obj in manifest.get("objects", []):
            key = obj["key"]
            sha256 = obj["sha256"]
            size = obj["size"]

            # Check presence
            headers = client.head_object(key)
            if headers:
                print(f"  ✓ {key} ({size:,} bytes, sha256:{sha256[:16]}...)")
            else:
                print(f"  ✗ {key} - MISSING")
                all_present = False

        # Verify signature if present
        sig_key = f"{manifest_key}.sig"
        sig_data = client.get_object(sig_key)
        if sig_data:
            print(f"\nSignature present: {sig_key}")
            # Verification would require VESSEL_HMAC_KEY
            print("  (Signature verification requires VESSEL_HMAC_KEY)")
        else:
            print(f"\n⚠ No signature found")

        print()
        if all_present:
            print("✓ Verification PASSED")
            return 0
        else:
            print("✗ Verification FAILED - missing objects")
            return 1

    except Exception as e:
        logger.error("Verification failed", error=str(e), exc_info=True)
        return 1


# ============================================================================
# Environment and CLI Entry Point
# ============================================================================

def print_setup_instructions():
    """Print R2 setup instructions when credentials missing."""
    print("\n=== R2 Cloudflare Setup Required ===\n", file=sys.stderr)
    print("Missing required environment variables.", file=sys.stderr)
    print("\n1. Create R2 bucket:", file=sys.stderr)
    print("   - Go to https://dash.cloudflare.com/", file=sys.stderr)
    print("   - Navigate to R2 > Create bucket", file=sys.stderr)
    print("   - Name: e.g., 'vessel-twin'", file=sys.stderr)
    print("\n2. Create API Token:", file=sys.stderr)
    print("   - Go to R2 > Overview > R2 API Tokens", file=sys.stderr)
    print("   - Create token with permissions:", file=sys.stderr)
    print("     * Account ID: (your account ID)", file=sys.stderr)
    print("     * Permissions: Admin Read & Write", file=sys.stderr)
    print("   - Save: Access Key ID, Secret Access Key, Account ID", file=sys.stderr)
    print("\n3. Set environment variables:", file=sys.stderr)
    print("   export R2_ACCOUNT_ID='your-account-id'", file=sys.stderr)
    print("   export R2_ACCESS_KEY_ID='your-access-key'", file=sys.stderr)
    print("   export R2_SECRET_ACCESS_KEY='your-secret-key'", file=sys.stderr)
    print("   export R2_BUCKET='vessel-twin'", file=sys.stderr)
    print("   export VESSEL_ID='your-vessel-id'", file=sys.stderr)
    print("   export VESSEL_HMAC_KEY='32-byte-hex-key'  # Optional, for signing", file=sys.stderr)
    print()


def check_env_vars() -> Tuple[bool, Dict[str, str]]:
    """Check for required environment variables."""
    missing = [var for var in REQUIRED_ENV_VARS if var not in os.environ]

    if missing:
        logger.error("Missing required environment variables", missing=missing)
        print_setup_instructions()
        return False, {}

    config = {var: os.environ[var] for var in REQUIRED_ENV_VARS}
    for var in OPTIONAL_ENV_VARS:
        if var in os.environ:
            config[var] = os.environ[var]

    return True, config


def parse_hmac_key(key_str: Optional[str]) -> Optional[bytes]:
    """Parse hex-encoded HMAC key."""
    if not key_str:
        return None

    try:
        key_bytes = bytes.fromhex(key_str)
        if len(key_bytes) != 32:
            logger.warn("HMAC key should be 32 bytes", got=len(key_bytes))
        return key_bytes
    except ValueError:
        logger.error("HMAC key must be hex-encoded")
        return None


def main() -> int:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: cloud_backup.py [--status|--day YYYY-MM-DD|--verify YYYY-MM-DD]", file=sys.stderr)
        print("  --status: Verify credentials and show status", file=sys.stderr)
        print("  --day YYYY-MM-DD: Bundle and upload day's data", file=sys.stderr)
        print("  --verify YYYY-MM-DD: Verify backup integrity", file=sys.stderr)
        return 2

    # Check environment
    ok, config = check_env_vars()
    if not ok:
        return 2

    # Parse HMAC key
    hmac_key = parse_hmac_key(config.get("VESSEL_HMAC_KEY"))

    # Create client
    client = R2Client(
        account_id=config["R2_ACCOUNT_ID"],
        access_key_id=config["R2_ACCESS_KEY_ID"],
        secret_access_key=config["R2_SECRET_ACCESS_KEY"],
        bucket=config["R2_BUCKET"],
        vessel_id=config["VESSEL_ID"],
    )

    command = sys.argv[1]

    if command == "--status":
        return cmd_status(client)
    elif command == "--day":
        if len(sys.argv) < 3:
            logger.error("--day requires YYYY-MM-DD argument")
            return 2
        day = sys.argv[2]
        data_dir = Path.cwd() / "data"
        return cmd_day(client, day, data_dir, hmac_key)
    elif command == "--verify":
        if len(sys.argv) < 3:
            logger.error("--verify requires YYYY-MM-DD argument")
            return 2
        day = sys.argv[2]
        return cmd_verify(client, day)
    else:
        logger.error("Unknown command", command=command)
        return 2


if __name__ == "__main__":
    sys.exit(main())
