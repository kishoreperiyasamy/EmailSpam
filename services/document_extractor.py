import os
import io
import re
import csv

# Graceful optional imports for serverless environments (e.g. Vercel)
try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from PIL import Image
except ImportError:
    Image = None


def extract_text_from_file(file_storage) -> dict:
    """
    Extracts text and metadata from uploaded brochures (PDF), documents (TXT, EML),
    and photo/image attachments or CSV datasets.
    Lightweight and resilient for serverless execution.
    """
    filename = getattr(file_storage, 'filename', '') or "uploaded_file"
    ext = os.path.splitext(filename)[1].lower()
    
    # Read file bytes
    file_bytes = file_storage.read()
    if hasattr(file_storage, 'seek'):
        file_storage.seek(0)  # Reset pointer
    
    file_size_kb = round(len(file_bytes) / 1024, 1)

    result = {
        "success": True,
        "filename": filename,
        "extension": ext,
        "file_size_kb": file_size_kb,
        "file_type": "unknown",
        "extracted_text": "",
        "page_count": 1,
        "urls_detected": [],
        "notes": []
    }

    # 1. PDF Brochures & Invoices
    if ext == '.pdf':
        result["file_type"] = "PDF Brochure / Document"
        pages_text = []
        urls = set()

        if pypdf:
            try:
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                result["page_count"] = len(reader.pages)
                for page in reader.pages:
                    txt = page.extract_text()
                    if txt:
                        pages_text.append(txt)
                full_text = "\n\n".join(pages_text).strip()
                result["extracted_text"] = full_text
                for u in re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', full_text):
                    urls.add(u)
                result["urls_detected"] = list(urls)
                result["notes"].append(f"Successfully extracted {len(pages_text)} page(s) from PDF.")
                return result
            except Exception as e:
                result["notes"].append(f"pypdf extraction notice: {e}")

        if pdfplumber:
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    result["page_count"] = len(pdf.pages)
                    for page in pdf.pages:
                        txt = page.extract_text()
                        if txt:
                            pages_text.append(txt)
                        if hasattr(page, 'hyperlinks') and page.hyperlinks:
                            for link in page.hyperlinks:
                                uri = link.get('uri')
                                if uri:
                                    urls.add(uri)
                    full_text = "\n\n".join(pages_text).strip()
                    result["extracted_text"] = full_text
                    for u in re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', full_text):
                        urls.add(u)
                    result["urls_detected"] = list(urls)
                    result["notes"].append(f"Successfully extracted {len(pages_text)} page(s) via pdfplumber.")
                    return result
            except Exception as e:
                result["success"] = False
                result["error"] = f"Failed to extract PDF content: {str(e)}"
                return result

        if not pypdf and not pdfplumber:
            result["success"] = False
            result["error"] = "PDF extraction module not available on server (install pypdf or pdfplumber)."
            return result

    # 2. Photos, Ad Banners, & Flyers (Image inspection)
    elif ext in ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']:
        result["file_type"] = "Photo / Image Ad"
        if Image:
            try:
                image = Image.open(io.BytesIO(file_bytes))
                width, height = image.size
                img_format = image.format or ext.replace('.', '').upper()
                result["notes"].append(f"Image format: {img_format}, dimensions: {width}x{height}px.")
                result["extracted_text"] = ""  # Client-side Tesseract.js handles high-speed OCR
            except Exception as e:
                result["notes"].append(f"Image validation note: {str(e)}")
        else:
            result["notes"].append("Photo attached (processed client-side via OCR).")

    # 3. Plain Text, EML, Markdown, or HTML files
    elif ext in ['.txt', '.eml', '.html', '.htm', '.md']:
        result["file_type"] = "Text / EML Document"
        try:
            decoded_text = file_bytes.decode('utf-8', errors='replace').strip()
            result["extracted_text"] = decoded_text
            raw_urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', decoded_text)
            result["urls_detected"] = list(set(raw_urls))
            result["notes"].append("Extracted plain text content.")
        except Exception as e:
            result["success"] = False
            result["error"] = f"Failed to read document: {str(e)}"
            return result

    # 4. CSV Spreadsheets & Datasets (Fast pure-Python parser)
    elif ext == '.csv':
        result["file_type"] = "CSV Dataset / Spreadsheet"
        try:
            # Decode file bytes
            try:
                decoded_csv = file_bytes.decode('utf-8')
            except UnicodeDecodeError:
                decoded_csv = file_bytes.decode('latin-1', errors='replace')

            # Parse CSV rows with standard library csv
            csv_file = io.StringIO(decoded_csv)
            sample = decoded_csv[:2048]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            except Exception:
                dialect = 'excel'

            csv_file.seek(0)
            reader = csv.reader(csv_file, dialect=dialect)
            rows = [row for row in reader if any(cell.strip() for cell in row)]

            if not rows:
                result["row_count"] = 0
                result["columns"] = []
                result["extracted_text"] = ""
                result["notes"].append("Uploaded CSV is empty.")
                return result

            # Extract header and data rows
            header_row = [str(c).strip() for c in rows[0]]
            data_rows = rows[1:]
            row_count = len(data_rows)
            result["row_count"] = row_count
            result["columns"] = header_row

            if row_count == 0:
                result["extracted_text"] = ""
                result["notes"].append("Uploaded CSV contains only headers.")
                return result

            # Detect subject and body columns
            col_map = {name.lower(): idx for idx, name in enumerate(header_row)}
            subj_idx = None
            for key in ['subject', 'title', 'headline', 'header', 'topic']:
                if key in col_map:
                    subj_idx = col_map[key]
                    break

            body_idx = None
            for key in ['body', 'message', 'text', 'content', 'email', 'mail', 'v2', 'sms', 'description', 'snippet', 'raw']:
                if key in col_map:
                    body_idx = col_map[key]
                    break

            # Fallback: find column with highest average character length
            if body_idx is None and header_row:
                num_cols = len(header_row)
                avg_lens = [0] * num_cols
                sample_data = data_rows[:30]
                if sample_data:
                    for r in sample_data:
                        for ci in range(min(len(r), num_cols)):
                            avg_lens[ci] += len(r[ci])
                    body_idx = avg_lens.index(max(avg_lens))

            emails_extracted = []
            preview_texts = []
            all_urls = set()

            for idx, row in enumerate(data_rows):
                s_val = row[subj_idx].strip() if (subj_idx is not None and subj_idx < len(row)) else ""
                b_val = row[body_idx].strip() if (body_idx is not None and body_idx < len(row)) else ""

                if not s_val and not b_val:
                    b_val = " | ".join(c.strip() for c in row if c.strip())

                # Collect detected URLs
                for u in re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', f"{s_val} {b_val}"):
                    all_urls.add(u)

                emails_extracted.append({
                    "row_index": idx + 1,
                    "subject": s_val,
                    "body": b_val
                })

                if idx < 20:
                    preview_texts.append(f"[Email #{idx + 1}]\nSubject: {s_val}\nContent: {b_val}")

            result["urls_detected"] = list(all_urls)
            result["emails_data"] = emails_extracted[:150]  # Store up to 150 items for batch prediction

            if row_count == 1:
                result["suggested_subject"] = emails_extracted[0]["subject"] or f"[CSV]: {filename}"
                result["extracted_text"] = emails_extracted[0]["body"]
                result["notes"].append("Extracted single email record from CSV.")
            else:
                result["suggested_subject"] = emails_extracted[0]["subject"] or f"[CSV Dataset: {filename} - {row_count} emails]"
                result["extracted_text"] = "\n\n----------------------------------------\n\n".join(preview_texts)
                result["notes"].append(f"Successfully extracted {row_count} row(s) from CSV. Columns: {', '.join(header_row[:5])}")

        except Exception as e:
            result["success"] = False
            result["error"] = f"Failed to parse CSV file: {str(e)}"
            return result

    else:
        result["file_type"] = "Attachment"
        result["notes"].append("Binary attachment detected.")

    return result
