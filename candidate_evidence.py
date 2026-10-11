"""Deterministic, lossless source spans for a single candidate-profile snapshot."""
import hashlib
import re

CATALOG_VERSION = "paragraphs-v2-kinds"


def evidence_kind(text, context):
    """Conservative source labels, not independent verification of profile claims."""
    context = context.casefold()
    lower = text.casefold().lstrip('-*+ ')
    if (re.search(r'\b(target roles?|career objectives?|career goals?|preferences?|aspirations?|desired roles?|interests?)\b', context)
            or re.match(r'(seeking|aspiring|interested in|targeting|would like|want to|goal:|preferred roles?:)', lower)):
        return 'aspiration'
    if re.search(r'\b(achievements?|accomplishments?|results?|measurable outcomes?)\b', context):
        return 'achievement'
    if re.search(r'\b(skills?|competencies|strengths|tools)\b', context):
        return 'skill'
    if re.search(r'\b(employment|work history|professional experience|career history|experience)\b', context):
        return 'employment'
    return 'unspecified'


def profile_digest(profile):
    return hashlib.sha256(profile.encode('utf-8')).hexdigest()


def build_evidence_catalog(profile):
    """Number paragraphs/bullets in source order; retain exact text and offsets.

    Markdown headings supply context, not stand-alone qualification evidence.
    IDs are scoped to this profile snapshot, identified by its SHA256 digest.
    """
    catalog = []
    section = ''
    headings = []
    pending = []

    def flush():
        if not pending:
            return
        start, end = pending[0][0], pending[-1][1]
        raw = profile[start:end]
        start += len(raw) - len(raw.lstrip())
        end -= len(raw) - len(raw.rstrip())
        catalog.append({'evidence_id': f'P{len(catalog) + 1:03d}',
                        'text': profile[start:end], 'start': start, 'end': end,
                        'section': section,
                        'evidence_kind': evidence_kind(profile[start:end], ' / '.join(title for _, title in headings))})
        pending.clear()

    for match in re.finditer(r'[^\r\n]+(?:\r\n|\r|\n|$)|[\r\n]+', profile):
        line = match.group(0)
        heading = re.match(r'^\s*(#{1,6})\s+(.+?)\s*$', line)
        if not line.strip() or heading:
            flush()
            if heading:
                level = len(heading.group(1))
                section = heading.group(2)
                headings[:] = [(depth, title) for depth, title in headings if depth < level]
                headings.append((level, section))
        else:
            if re.match(r'^\s*(?:[-*+]|\d+[.)])\s+', line):
                flush()
            pending.append((match.start(), match.end()))
    flush()
    return catalog
