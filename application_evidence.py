"""Shared candidate IDs, extractive tailoring and bounded grammatical rewrites.

IDs establish provenance, not entailment of arbitrary model-written prose.
"""
import hashlib
import re

from application_documents import ApplicationDocuments


def document_catalog(profile):
    from application_rendering import catalog_for_documents
    return catalog_for_documents(profile)


def first_person(text):
    """Closed grammatical transformations; no inferred facts or stronger verbs."""
    text = re.sub(r"\s+", " ", text).strip()
    actions = r"(?:Coordinated|Led|Managed|Developed|Built|Created|Implemented|Supported|Trained|Delivered|Owned|Operated|Improved|Reduced|Increased|Designed|Organized|Collaborated|Worked|Maintained|Analyzed|Assisted|Identified|Documented)"
    first_sentence = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)[0]
    if re.match(actions + r"\b", text) and not re.search(
            r"\b(?:by|was|were|is|are|includes?|not|responsibility|responsibilities)\b", first_sentence, re.I):
        return "I " + text[0].lower() + text[1:]
    return text


def document_digest(documents):
    return hashlib.sha256(documents.model_dump_json().encode("utf-8")).hexdigest()


def require_validated(documents):
    if not isinstance(documents, ApplicationDocuments) or documents._validated_digest != document_digest(documents):
        raise ValueError("Document snapshot is unvalidated or changed after validation. Nothing was exported.")
    from application_rendering import validate_quality
    validate_quality(documents)


def resolve_documents(draft, profile, posting=""):
    from application_rendering import render_application
    documents = render_application(draft, profile, posting)
    documents._validated_digest = document_digest(documents)
    return documents
