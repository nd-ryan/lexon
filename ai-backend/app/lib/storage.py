"""Tigris (S3-compatible) object storage client for file uploads."""
import os
import logging
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


logger = logging.getLogger(__name__)

# Lazily initialize the S3 client to avoid issues at import time when env vars aren't set
_s3_client: Optional[boto3.client] = None

BUCKET = os.getenv("TIGRIS_BUCKET", "lexon-uploads")


def _get_s3_client():
    """Get or create the S3 client."""
    global _s3_client
    if _s3_client is None:
        endpoint_url = os.getenv("TIGRIS_ENDPOINT_URL")
        if not endpoint_url:
            raise RuntimeError("TIGRIS_ENDPOINT_URL environment variable not set")
        
        _s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


def upload_file(case_id: str, filename: str, content: bytes) -> str:
    """
    Upload file to Tigris and return the object key.
    
    Args:
        case_id: The case UUID to use as prefix
        filename: Original filename (used for extension and Content-Disposition)
        content: File content as bytes
        
    Returns:
        The object key (path) in the bucket
    """
    # Use case_id as the key prefix for easy retrieval
    # Include original extension for proper content handling
    ext = os.path.splitext(filename)[1] or ""
    key = f"cases/{case_id}{ext}"
    
    s3 = _get_s3_client()
    
    # Determine content type based on extension
    content_type = "application/octet-stream"
    ext_lower = ext.lower()
    if ext_lower == ".pdf":
        content_type = "application/pdf"
    elif ext_lower in (".docx", ".doc"):
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext_lower == ".txt":
        content_type = "text/plain"
    
    try:
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=content,
            ContentType=content_type,
            ContentDisposition=f'attachment; filename="{filename}"',
        )
        logger.info(f"Uploaded file to Tigris: {key} ({len(content)} bytes)")
        return key
    except ClientError as e:
        logger.error(f"Failed to upload file to Tigris: {e}")
        raise


def download_file(key: str) -> bytes:
    """
    Download file content from Tigris by key.
    
    Args:
        key: The object key (path) in the bucket
        
    Returns:
        File content as bytes
    """
    s3 = _get_s3_client()
    
    try:
        response = s3.get_object(Bucket=BUCKET, Key=key)
        content = response["Body"].read()
        logger.info(f"Downloaded file from Tigris: {key} ({len(content)} bytes)")
        return content
    except ClientError as e:
        logger.error(f"Failed to download file from Tigris: {e}")
        raise


def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """
    Generate a presigned URL for direct download.
    
    Args:
        key: The object key (path) in the bucket
        expires_in: URL expiration time in seconds (default 1 hour)
        
    Returns:
        Presigned URL string
    """
    s3 = _get_s3_client()
    
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
        logger.info(f"Generated presigned URL for: {key}")
        return url
    except ClientError as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise


def delete_file(key: str) -> bool:
    """
    Delete a file from Tigris.
    
    Args:
        key: The object key (path) in the bucket
        
    Returns:
        True if deleted successfully
    """
    s3 = _get_s3_client()
    
    try:
        s3.delete_object(Bucket=BUCKET, Key=key)
        logger.info(f"Deleted file from Tigris: {key}")
        return True
    except ClientError as e:
        logger.error(f"Failed to delete file from Tigris: {e}")
        raise
