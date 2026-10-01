import os
import io
import re

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from PIL import Image

def extract_text_from_file(file_storage) -> dict:
    """
    Extracts text and metadata from uploaded brochures (PDF), documents (TXT, EML),
    and photo/image attachments.
    """
    filename = file_storage.filename or "uploaded_file"
    ext = os.path.splitext(filename)[1].lower()
    
    # Read file bytes
    file_bytes = file_storage.read()
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
        if not pdfplumber:
            result["success"] = False
            result["error"] = "PDF extraction module (pdfplumber) is not available. Please install it using 'pip install pdfplumber'."
            return result
        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages_text = []
                urls = set()
                result["page_count"] = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages, 1):
                    # Extract page text
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                    
                    # Extract hyperlink annotations if present
                    if hasattr(page, 'hyperlinks') and page.hyperlinks:
                        for link in page.hyperlinks:
                            uri = link.get('uri')
                            if uri:
                                urls.add(uri)

                full_text = "\n\n".join(pages_text).strip()
                result["extracted_text"] = full_text

                # Find any raw URLs in extracted text
                raw_urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', full_text)
                for u in raw_urls:
                    urls.add(u)

                result["urls_detected"] = list(urls)
                result["notes"].append(f"Successfully extracted {len(pages_text)} page(s) from PDF brochure.")
        except Exception as e:
            result["success"] = False
            result["error"] = f"Failed to extract PDF content: {str(e)}"
            return result

    # 2. Photos, Ad Banners, & Flyers (Image inspection)
    elif ext in ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']:
        result["file_type"] = "Photo / Image Ad"
        try:
            image = Image.open(io.BytesIO(file_bytes))
            width, height = image.size
            img_format = image.format or ext.replace('.', '').upper()
            result["notes"].append(f"Image format: {img_format}, dimensions: {width}x{height}px.")
            result["extracted_text"] = ""  # Client-side Tesseract.js handles high-speed OCR
        except Exception as e:
            result["notes"].append(f"Basic image validation note: {str(e)}")

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

    # 4. CSV Spreadsheets & Datasets
    elif ext == '.csv':
        result["file_type"] = "CSV Dataset / Spreadsheet"
        try:
            import pandas as pd

            # Decode bytes with fallback encoding
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8')
            except Exception:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding='latin-1')

            row_count = len(df)
            result["row_count"] = row_count
            result["columns"] = [str(c) for c in df.columns]

            if row_count == 0:
                result["extracted_text"] = ""
                result["notes"].append("Uploaded CSV is empty.")
                return result

            # Detect subject and body columns
            col_map = {str(col).strip().lower(): col for col in df.columns}
            
            subj_col = None
            for key in ['subject', 'title', 'headline', 'header', 'topic']:
                if key in col_map:
                    subj_col = col_map[key]
                    break
            
            body_col = None
            for key in ['body', 'message', 'text', 'content', 'email', 'mail', 'v2', 'sms', 'description', 'snippet', 'raw']:
                if key in col_map:
                    body_col = col_map[key]
                    break

            # If no obvious body column, pick the text column with highest average string length
            if not body_col:
                text_cols = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
                if text_cols:
                    body_col = max(text_cols, key=lambda c: df[c].dropna().astype(str).str.len().mean() if len(df[c].dropna()) > 0 else 0)

            emails_extracted = []
            preview_texts = []
            all_urls = set()

            for idx, row in df.iterrows():
                s_val = str(row[subj_col]).strip() if (subj_col and pd.notna(row[subj_col])) else ""
                b_val = str(row[body_col]).strip() if (body_col and pd.notna(row[body_col])) else ""
                
                # If neither column matched, combine all cell values
                if not s_val and not b_val:
                    row_vals = [str(val).strip() for val in row.dropna() if str(val).strip()]
                    b_val = " | ".join(row_vals)

                # Collect detected URLs
                for u in re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', f"{s_val} {b_val}"):
                    all_urls.add(u)

                emails_extracted.append({
                    "row_index": int(idx) + 1,
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
                result["notes"].append(f"Successfully extracted {row_count} row(s) from CSV. Columns: {', '.join(str(c) for c in df.columns[:5])}")

        except Exception as e:
            result["success"] = False
            result["error"] = f"Failed to parse CSV file: {str(e)}"
            return result

    else:
        result["file_type"] = "Attachment"
        result["notes"].append("Binary attachment detected.")

    return result
