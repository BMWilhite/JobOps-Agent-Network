"""Employer-facing formatting over verified source selections, never free facts."""
import re
from collections import Counter

from application_documents import ApplicationDocuments, DocumentEvidence, SourceApplicationDocuments
from candidate_evidence import build_evidence_catalog, profile_digest

METADATA = re.compile(r"\b(?:do not|don't|never|must not|only claim|use only|desired roles?|target roles?|career goals?|aspirations?|not independently verified|not evidenced|no .{0,35}(?:experience|background)|verification checklist|needs verification|prompt guidance|internal instructions?|audited realized|results are estimated|profile limitations?|candidate limitations?|candidate profile|source IDs?|internal validation|validation checks?)\b|^\s*limitations?:", re.I)
META_SECTION = re.compile(r"\b(?:instructions?|guidance|limitations?|preferences?|target roles?|verification|guardrails|writing rules|metadata)\b", re.I)
MAX_BULLET_WORDS = 45


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", text)).strip().replace("**", "")


def content_units(entry):
    # Split responsibilities, not numbers or abbreviations. Semicolon-separated
    # facts are separate bullets; the complete source remains in the sidecar.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])|;\s+|\n\s*(?:[-*+]\s+)", entry["text"])
    return [{"index": i, "text": clean(text),
             "publishable": bool(clean(text)) and not METADATA.search(text)
                 and not META_SECTION.search(entry["section"])}
            for i, text in enumerate(parts, 1)]


def catalog_for_documents(profile):
    result, section, internal = [], None, False
    for entry in build_evidence_catalog(profile):
        if entry['section'] != section:
            section, internal = entry['section'], False
        label = clean(entry['text'])
        if label.endswith(':') and '\n' not in entry['text']:
            internal = bool(META_SECTION.search(label))
        units = content_units(entry)
        if internal or label.endswith(':'):
            units = [dict(unit, publishable=False) for unit in units]
        result.append(dict(entry, content_units=units))
    return result


def job_identity(posting):
    company = re.search(r"^Company:\s*(.+)$", posting, re.M | re.I)
    title = re.search(r"^(?:Job title|Title|Role):\s*(.+)$", posting, re.M | re.I)
    if company and title:
        return clean(company[1]), clean(title[1])
    first = next((line.strip().lstrip('# ') for line in posting.splitlines() if line.strip()), '')
    pair = re.split(r"\s+[—–]\s+", first, maxsplit=1)
    if len(pair) == 2:
        return clean(pair[0]), clean(pair[1]).rstrip('.')
    return "[Employer — verify]", "[Role — verify]"


def identity(catalog, profile):
    name, contacts, refs = None, [], []
    for entry in catalog.values():
        if META_SECTION.search(entry["section"]) or entry["evidence_kind"] == "aspiration":
            continue
        text = clean(entry["text"])
        match = re.search(r"(?:^|\s)(?:Applicant name|Full name|Name):[ \t]*([^;|,\n]+)", entry["text"].replace('**', ''), re.I)
        contact_section = re.search(r"\b(?:contact|personal details|identity)\b", entry["section"], re.I)
        if match:
            name = clean(match[1])
            refs.append((entry, name))
        elif contact_section and not name:
            possible = text.split(',')[0].split('|')[0].strip()
            if re.fullmatch(r"[A-Za-zÀ-ÿ.'-]+(?: [A-Za-zÀ-ÿ.'-]+){1,4}", possible):
                name = possible
                refs.append((entry, name))
        # Do not collect an employer's contact details from employment passages.
        if contact_section or match or re.match(r"(?:Email|Phone|LinkedIn|Location):", text, re.I):
            values = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\d ()-]{7,}\d)|https?://(?:www\.)?linkedin\.com/[^\s,|]+", text)
            for value in values:
                if value not in contacts:
                    contacts.append(value)
                    refs.append((entry, value))
    if not name:
        # Explicit identity headings are metadata outside the paragraph catalog.
        # Python resolves their literal offsets; no model quotation or invented ID.
        match = re.search(r'^#{1,3}\s+(?:Applicant name|Candidate name|Full name|Name):[ \t]*(.+)$', profile, re.M | re.I)
        if match:
            name = clean(match[1])
            refs.append(({'evidence_id': '', 'text': match[0], 'section': 'Identity',
                          'start': match.start(), 'end': match.end()}, name))
    reminders = []
    if not name:
        name = "[Applicant name — verify]"
        reminders.append("Replace the applicant-name placeholder using verified personal information.")
    if not any('@' in value or re.search(r'\d[\d ()-]{7,}\d', value) for value in contacts):
        contacts.append("[Email / phone — verify]")
        reminders.append("Replace the contact placeholder with verified email or phone information.")
    return name, " | ".join(contacts), refs, reminders


def employment_fields(entry, catalog):
    context = clean(entry["section"])
    group = [e for e in catalog.values() if e["section"] == entry["section"]]
    if re.fullmatch(r'employment|experience|work history|professional experience', context, re.I):
        position = group.index(entry)
        starts = [i for i, e in enumerate(group) if re.search(
            r'(?:Company|Employer):|.+?\s+(?:at|for)\s+.+?,\s*\d{4}', e['text'])]
        start = max((i for i in starts if i <= position), default=0)
        end = min((i for i in starts if i > position), default=len(group))
        group = group[start:end]
    fields = {}
    for e in group:
        # A company heading plus an actual role/date passage is verified job
        # identity. Keep multiline titles intact; target-role headings are not jobs.
        pipe = re.fullmatch(r'(.+?)\s*\|\s*(\d{4}\s*[-–]\s*(?:\d{4}|Present))\s*',
                            clean(e['text']), re.I)
        if (pipe and e['evidence_kind'] == 'employment'
                and not META_SECTION.search(context)
                and not re.search(r'\bproject\b', context, re.I)):
            fields.update(title=pipe[1].strip(), dates=pipe[2].strip())
            if not re.fullmatch(r'employment|experience|work history|professional experience', context, re.I):
                fields['company'] = context
        for key, pattern in [("company", r"(?:Company|Employer):\s*([^\n;]+)"),
                             ("title", r"(?:Actual job title|Job title|Title|Role):\s*([^\n;]+)"),
                             ("dates", r"Dates?:\s*([^\n;]+)")]:
            match = re.search(r'^[ \t]*(?:[-*+]\s*)?' + pattern, e["text"].replace('**', ''), re.I | re.M)
            if match and not re.match(r'(?:desired|target|seeking|aspiring)\b', clean(match[1]), re.I):
                fields[key] = clean(match[1])
    if not fields:
        # Preserve explicit source labels; never substitute the target job title.
        combined = context if re.search(r"[—–]|\d{4}", context) else ' '.join(clean(e['text']) for e in group)
        match = re.search(r"(.+?)\s+(?:at|for)\s+(.+?),\s*(\d{4}.*?)(?:\.|$)", combined)
        if match:
            fields = {"title": match[1], "company": match[2], "dates": match[3]}
        else:
            pair = re.split(r"\s+[—–]\s+", context, maxsplit=1)
            if len(pair) == 2:
                fields["company"] = pair[0]
                title_date = pair[1].rsplit(', ', 1)
                fields["title"] = title_date[0]
                if len(title_date) == 2 and re.search(r"\d{4}", title_date[1]):
                    fields["dates"] = title_date[1]
    return fields


def role_metadata(text):
    return bool(re.match(r'(?:Company|Employer|Actual job title|Job title|Title|Role|Dates?):', text, re.I)
                or re.fullmatch(r'.+?\s*\|\s*\d{4}\s*[-–]\s*(?:\d{4}|Present)', text, re.I)
                or re.search(r'.+?\s+(?:at|for)\s+.+?,\s*\d{4}', text))


def onboarding_outcome(text):
    # Only collapse the two representations of an onboarding-time outcome,
    # scoped to the same job. Other onboarding/production achievements survive.
    if not re.search(r'onboarding[ -]time', text, re.I):
        return None
    if re.search(r'\bfrom\b.+\bto\b', text, re.I) and re.search(r'\b(?:days|hours)\b', text, re.I):
        return 'duration'
    if '%' in text and re.search(r'improv|reduc', text, re.I):
        return 'percentage'
    return None


def accomplishment_score(text, terms):
    action = bool(re.match(r'(?:Reduced|Improved|Identified|Redesigned|Built|Developed|Implemented|Created|Streamlined|Increased|Led)\b', text, re.I))
    result = bool(re.search(r'\d\s*%|\$\s*\d|\b\d+(?:-\d+)?\s+(?:days|hours|employees|clients)\b', text, re.I))
    responsibility = bool(re.match(r'(?:Founded|Operate|Served|Coordinated|Managed|Supported|Trained|Evaluated|Worked|Maintained|Organized)\b', text, re.I))
    return 12 * action + 5 * responsibility + 5 * result + 10 * (onboarding_outcome(text) == 'duration') + len(terms & set(re.findall(r'[a-z]{4,}', text.lower())))


def validate_quality(documents):
    resume, letter = documents.resume_markdown, documents.cover_letter_markdown
    for text in (resume, letter):
        if METADATA.search(text) or re.search(r"\bP\d{3,}\b", text):
            raise ValueError("Document quality check: internal instructions or evidence references leaked. Nothing was exported.")
    lines = [line[2:] for line in resume.splitlines() if line.startswith('- ')]
    if any(len(line.split()) > MAX_BULLET_WORDS for line in lines) or len(lines) > 18:
        raise ValueError("Document quality check: oversized or excessive resume bullets. Nothing was exported.")
    if len(resume.split()) > 850 or len(letter.split()) > 400:
        raise ValueError("Document quality check: document is too long. Nothing was exported.")
    if not resume.startswith('# ') or not ('@' in resume or '[Email / phone — verify]' in resume or re.search(r"\d[\d ()-]{7,}\d", resume)):
        raise ValueError("Document quality check: applicant identity/contact or placeholders missing. Nothing was exported.")
    if resume.splitlines()[0] in ('# Resume', '#'):
        raise ValueError("Document quality check: applicant name or placeholder missing. Nothing was exported.")


def render_application(draft, profile, posting):
    if not isinstance(draft, SourceApplicationDocuments):
        raise ValueError("Expected source-ID document selections; unsupported response format. Nothing was exported.")
    from application_evidence import first_person
    catalog = {e['evidence_id']: e for e in catalog_for_documents(profile)}
    evidence, reminders = [], []
    name, contact, identity_refs, identity_reminders = identity(catalog, profile)
    reminders.extend(identity_reminders)
    company, role = job_identity(posting)
    if '[Employer' in company or '[Role' in role:
        reminders.append("Replace employer/role placeholders using the selected posting.")

    def cite(entry, claim, document, index=None):
        evidence.append(DocumentEvidence(document=document, claim=claim,
            evidence_id=entry['evidence_id'], source_quote=entry['text'],
            source_context=entry['section'], source_unit_index=index,
            source_start=entry.get('start'), source_end=entry.get('end')))

    for entry, claim in identity_refs:
        for document in ('resume', 'cover_letter'):
            cite(entry, claim, document)

    def selected(block, document, count, heading=None):
        prefix = f"{document} block {count}"
        if not block.evidence_ids or len(set(block.evidence_ids)) != len(block.evidence_ids):
            raise ValueError(f"{prefix}: missing or duplicate candidate evidence IDs. Nothing was exported.")
        if block.unit_indices and len(block.evidence_ids) != 1:
            raise ValueError(f"{prefix}: unit indices require one source ID. Nothing was exported.")
        result = []
        for eid in block.evidence_ids:
            entry = catalog.get(eid)
            if entry is None:
                raise ValueError(f"{prefix}: unrecognized candidate evidence ID. Posting evidence cannot establish candidate experience. Nothing was exported.")
            if entry['evidence_kind'] == 'aspiration' or re.search(r"\bI (?:want|hope|aspire|aim|am seeking|would like)\b", entry['text'], re.I):
                raise ValueError(f"{prefix}: aspiration evidence cannot establish candidate experience. Nothing was exported.")
            if heading in {'Experience', 'Achievements'} and entry['evidence_kind'] == 'skill':
                raise ValueError(f"{prefix}: skills evidence cannot establish employment or achievements. Nothing was exported.")
            if heading == 'Experience' and re.search(r'\bproject\b', entry['section'], re.I):
                raise ValueError(f"{prefix}: project evidence belongs in Projects, not employment. Nothing was exported.")
            if heading in {'Education', 'Certifications'} and not re.search(r"\b(education|academic|degree|certifications?|credentials?)\b", entry['section'], re.I):
                raise ValueError(f"{prefix}: education or credential source context is missing. Nothing was exported.")
            units = entry['content_units']
            if block.unit_indices:
                if len(set(block.unit_indices)) != len(block.unit_indices) or any(i < 1 or i > len(units) for i in block.unit_indices):
                    raise ValueError(f"{prefix}: invalid source unit indices. Nothing was exported.")
                units = [units[i - 1] for i in block.unit_indices]
            if any(not u['publishable'] for u in units):
                reminders.append("Internal guidance and profile limitations were excluded from employer-facing content.")
            units = [u for u in units if u['publishable']]
            if re.search(r'\b(?:contact|personal details|identity)\b', entry['section'], re.I):
                # Contact facts have already been resolved into the document header.
                continue
            if document == 'cover_letter':
                units = [u for u in units if not re.match(
                    r'(?:Company|Employer|Actual job title|Job title|Title|Role|Dates?|Name|Email|Phone):', u['text'], re.I)
                    and not re.fullmatch(r'.+?\s*\|\s*\d{4}\s*[-–]\s*(?:\d{4}|Present)', u['text'], re.I)]
            if not block.unit_indices:
                terms = set(re.findall(r'[a-z]{4,}', posting.lower()))
                units = sorted(units, key=lambda u: -len(terms & set(re.findall(r'[a-z]{4,}', u['text'].lower()))))[:5 if document == 'resume' else 2]
            for unit in units:
                text = unit['text']
                if len(text.split()) > MAX_BULLET_WORDS:
                    raise ValueError(f"{prefix}: source unit exceeds 45 words; select a shorter supported unit. Nothing was exported.")
                if re.search(r'\d', text) and not re.search(r'\d{4}\s*[-–]\s*\d{4}', text) and re.search(r'estimat|potential|not.*(?:audited|realized)', entry['text'], re.I):
                    if not re.search(r'estimat|potential|identified', text, re.I):
                        text = text.rstrip('.') + ' (estimated).'
                    if re.search(r'savings|cost', text, re.I) and re.search(r'potential|not.*realized', entry['text'], re.I) and not re.search(r'potential|identified', text, re.I):
                        raise ValueError(f"{prefix}: financial claim conflicts with potential/unrealized source caveats. Select an explicit estimated-potential unit. Nothing was exported.")
                    reminders.append("Confirm estimated results and identified savings potential; do not convert them to realized or audited savings.")
                result.append((entry, unit['index'], text))
        return result

    resume = ['# ' + name, contact]
    total, counts, seen = 0, Counter(), set()
    for section in draft.resume_sections:
        if section.heading == 'Contact':
            continue
        body, last_context = [], None
        candidates = []
        for count, block in enumerate(section.blocks, 1):
            candidates.extend(selected(block, 'resume', count, section.heading))
        if section.heading == 'Experience':
            # Group actual jobs before ranking their accomplishments. Prefer
            # quantified results over low-impact routine responsibilities.
            jobs = {}
            terms = set(re.findall(r'[a-z]{4,}', posting.lower()))
            for item in candidates:
                fields = employment_fields(item[0], catalog)
                key = tuple(fields.get(k, '') for k in ('company', 'title', 'dates')) if fields else item[0]['section']
                jobs.setdefault(key, []).append(item)
            candidates = [item for group in jobs.values() for item in sorted(group, key=lambda item:
                -accomplishment_score(item[2], terms))]
        def outcome_context(entry):
            fields = employment_fields(entry, catalog)
            return tuple(fields.get(k, '') for k in ('company', 'title', 'dates')) if fields else entry['section']
        duration_contexts = {outcome_context(item[0]) for item in candidates if onboarding_outcome(item[2]) == 'duration'}
        for entry, index, text in candidates:
            key = (entry['evidence_id'], index)
            if key in seen:
                continue
            if onboarding_outcome(text) == 'percentage' and outcome_context(entry) in duration_contexts:
                continue
            fields = employment_fields(entry, catalog) if section.heading == 'Experience' else {}
            context = tuple(fields.get(key, '') for key in ('company', 'title', 'dates')) if fields else entry['section']
            def cite_fields():
                for claim in fields.values():
                    origin = next((e for e in catalog.values() if e['section'] == entry['section']
                                   and (claim in clean(e['text']) or claim in clean(e['section']))), entry)
                    cite(origin, claim, 'resume')
            # Source identity lines belong in the job header, not giant bullets.
            if role_metadata(text):
                if not fields:
                    continue
                if context != last_context:
                    body.extend(['### ' + fields.get('company', '[Employer — verify]'),
                        fields.get('title', '[Actual job title — verify]') + ' | ' + fields.get('dates', '[Employment dates — verify]')])
                    last_context = context
                cite_fields()
                continue
            if total >= 18 or (section.heading == 'Experience' and counts[context] >= 5):
                reminders.append("Additional source facts were omitted to keep the resume focused.")
                continue
            if section.heading == 'Experience' and context != last_context:
                body.extend(['### ' + fields.get('company', '[Employer — verify]'),
                    fields.get('title', '[Actual job title — verify]') + ' | ' + fields.get('dates', '[Employment dates — verify]')])
                cite_fields()
                if len(fields) < 3:
                    reminders.append("Verify and replace missing employer, actual job title or employment-date placeholders.")
                last_context = context
            if section.heading == 'Projects' and context != last_context:
                body.append('### ' + clean(entry['section']))
                last_context = context
            body.append('- ' + text)
            cite(entry, text, 'resume', index)
            seen.add(key)
            total += 1
            counts[context] += 1
        if body:
            resume.extend(['## ' + section.heading] + body)
    if not total:
        raise ValueError("No publishable candidate accomplishments or skills selected. Nothing was exported.")

    examples, letter_seen = [], set()
    for count, block in enumerate(draft.cover_letter_paragraphs, 1):
        for entry, index, text in selected(block, 'cover_letter', count):
            key = (entry['evidence_id'], index)
            if key in letter_seen or len(examples) >= 4:
                continue
            claim = first_person(text) if entry['evidence_kind'] in {'employment', 'achievement'} else text
            if entry['evidence_kind'] == 'skill':
                claim = 'My skills include ' + text[0].lower() + text[1:]
            elif claim == text and re.match(r'.+?\s+(?:at|for)\s+.+?,\s*\d{4}', text):
                claim = 'My experience includes work as ' + text[0].lower() + text[1:]
            elif claim == text and text.startswith('Identified savings potential'):
                claim = 'My work identified savings potential' + text[len('Identified savings potential'):]
            examples.append(claim.rstrip('.') + '.')
            cite(entry, claim, 'cover_letter', index)
            letter_seen.add(key)
    if not examples:
        raise ValueError("No publishable cover-letter evidence selected. Nothing was exported.")
    middle = [' '.join(examples[:2])]
    if len(examples) > 2:
        middle.append('I would bring this practical perspective to the priorities of the role. ' + ' '.join(examples[2:]))
    letter = ['# ' + name, contact, 'Dear Hiring Team,',
        f'I am applying for the {role} position at {company}. I am drawn to the opportunity to contribute to your team.',
        middle[0] + ' These experiences shape how I would approach the responsibilities described in your posting.'] + middle[1:] + [
        f'I would welcome a conversation about how these experiences could support {company} in this role. Thank you for considering my application.',
        'Sincerely,', name]
    description = re.split(r'Full job description:\s*', posting, maxsplit=1, flags=re.I)[-1]
    priorities = [topic for topic in ('operational workflows', 'process improvements', 'systems', 'implementation', 'onboarding', 'reporting')
                  if re.search(r'\b' + re.escape(topic) + r'\b', description, re.I)][:2]
    if priorities:
        sentence = 'Your posting emphasizes ' + ' and '.join(priorities) + '.'
        letter[3] += ' ' + sentence
        evidence.append(DocumentEvidence(document='cover_letter', claim=sentence,
            source='job_posting', source_quote=posting, evidence_id='',
            source_context='Selected posting priorities', source_start=0, source_end=len(posting)))
    documents = ApplicationDocuments(resume_markdown='\n\n'.join(resume), cover_letter_markdown='\n\n'.join(letter),
        verification_items=list(dict.fromkeys(draft.verification_items + reminders)), evidence=evidence,
        profile_sha256=profile_digest(profile))
    validate_quality(documents)
    return documents
