try:
    import pymupdf as fitz
except ImportError:
    import fitz

import logging               # Python's built-in logging system
from pathlib import Path     # Safe cross-platform file path handling

from config import LOG_LEVEL, LOG_TO_CONSOLE, LOG_FILE

logger = logging.getLogger(__name__)

def setup_logging():
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    handlers = []
    
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    handlers.append(file_handler)
    
    if LOG_TO_CONSOLE:
        console_handler = logging.StreamHandler()
        handlers.append(console_handler)
        
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers
    )
    
def extract_text_from_pdf(pdf_path: Path | str) -> list[str]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf_path}")
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if not str(pdf_path).lower().endswith('.pdf'):
        logger.error(f"File is not a PDF: {pdf_path}")
        raise ValueError(f"File is not a PDF: {pdf_path}")

    logger.info(f"Opening PDF: {pdf_path}")
    
    pages_text = []
    
    with fitz.open(pdf_path) as pdf_document:
        
        total_pages = len(pdf_document)
        logger.info(f"PDF has {total_pages} pages")

        for page_number in range(total_pages):
            page = pdf_document[page_number]
            raw_text = page.get_text("text")
            cleaned = clean_page_text(raw_text)
            
            if cleaned:
                pages_text.append(cleaned)
                logger.debug(f"Page {page_number + 1}/{total_pages} extracted "
                             f"({len(cleaned)} characters)")
            else: 
                logger.debug(f"Page {page_number + 1}/{total_pages} skipped "
                             f"(empty or image-only)")

        logger.info(f"Extraction complete. {len(pages_text)} pages with text found.")
        return pages_text

def clean_page_text(raw_text: str) -> str:
    import re
    text = re.sub(r'-\n', '', raw_text) #remove next line texts
     
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text) #replace single newlines with a space
    
    text = re.sub(r'\n{3,}', '\n\n', text) #Collapse multiple blank lines into one
    
    text = text.strip() #remove leading/trailling whitespace
    
    return text
     
def get_pdf_metadata(pdf_path: Path | str) -> dict:
    pdf_path = Path(pdf_path)
    with fitz.open(pdf_path) as doc:
        meta = doc.metadata
        
    return {
        "title":  meta.get("title", "Unknown Title"),
        "author": meta.get("author", "Unknown Author"),
        "pages":  meta.get("pageCount", 0)
    }
            
            