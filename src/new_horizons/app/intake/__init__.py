"""Document intake — attach a document, OCR it, extract its fields, reconcile
them against the five source systems, and raise a KB-grounded alert.

    samples.py   print the two demo invoices (scanned, image-only PDFs)
    read.py      text layer or OCR  -> text
    extract.py   VLM structuring, every figure verified against the OCR text
    pipeline.py  process(): read -> extract -> reconcile -> terms -> compose
"""
