def upload_to_s3(filename: str, content: bytes) -> str:
    return f"s3://bucket/{filename}"

def parse_pdf_to_text(content: bytes) -> str:
    return content.decode("utf-8", errors="ignore")[:1000]
