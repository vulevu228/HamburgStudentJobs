"""Rule-based facts from a posting. They always run; the AI step (ai.py) refines some of them when enabled."""
import re

import catalog

I = re.IGNORECASE
NOT_STUDENT = r"ausbildung|azubi|auszubildend|apprentice|schüler|schulpraktikum|fsj|bufdi|freiwilliges soziales|freiwilligendienst|abiturient|duales studium|dual student"


def level_of(title, hint=""):
    t = f"{title} {hint}"
    if re.search(NOT_STUDENT, title, I):
        return None
    if re.search(r"werkstud|werksstud|working student|student assistant|studentische|working_student|hiwi", t, I):
        return "Werkstudent"
    if re.search(r"thesis|abschlussarbeit|bachelorarbeit|masterarbeit", t, I):
        return "Thesis"
    internship = r"intern(ship)?\b|internhsip|praktik|praktikum|praxissemester"
    if re.search(internship, title, I):
        return "Internship"
    if re.search(r"\bsenior\b|\blead\b|head of|principal|director|teamleit|leitung|leiter", title, I):
        return None  # e.g. "Senior Student Recruiter", "Junior bis Senior"
    # side jobs aimed at students (cafés, retail, events, tutoring...) - title must say so explicitly.
    # Checked before the source's own type: the job agency files e.g. Lidl's "Studentenjob" as PRAKTIKUM_TRAINEE.
    if re.search(r"studentenjob|studentjob|student job|jobs? für studierende|für studierende|\bstudent(\*in|in)?\b|aushilfe.{0,20}student|minijob.{0,20}student",
                 title, I):
        return "Student side job"
    if re.search(r"referendar", title, I):
        return "Junior / Trainee"  # post-degree legal/teaching training; the job agency files it as PRAKTIKUM_TRAINEE
    if re.search(internship + "|PRAKTIKUM_TRAINEE", hint, I):
        return "Internship"
    if re.search(r"junior|entry[- ]level|graduate|trainee|berufseinsteiger|absolvent|young professional|volont", t, I):
        return "Junior / Trainee"
    return None


def language_of(text):
    if len(text) < 300:
        return "Unknown"
    words = re.findall(r"[a-zäöüß]+", text.lower())
    en = sum(w in {"the", "and", "you", "with", "our", "for", "your", "are", "will", "we", "of", "to"} for w in words)
    de = sum(w in {"und", "die", "der", "sie", "mit", "wir", "für", "ihre", "das", "bei", "zu", "ein"} for w in words)
    return "EN" if en > de * 1.2 else "DE" if de > en * 1.2 else "Mixed"


def field_of(title):
    for name, rx in catalog.FIELD_RULES:
        if re.search(rx, title, I):
            return name
    return "Other"


def skills_in(text):
    return [lbl for lbl, rx in catalog.SKILLS.items()
            if re.search(rx, text, 0 if lbl in catalog.CASE_SENSITIVE else I)]


def german_of(text, lang):
    if lang == "DE" or re.search(catalog.GERMAN_REQUIRED, text, I):
        return "required"
    if re.search(catalog.GERMAN_NICE, text, I):
        return "a plus"
    return "not mentioned"


ENGLISH_ASKED = (r"(?:englisch\w*|english)"  # the word itself, then a sign it is a requirement, in either order
                 r"(?=[^.\n]{0,60}(kenntnis|sprach|fließend|verhandlungssicher|wort und schrift|c1|c2|b2|fluent|proficien|skills|level|required|plus|vorteil|wünschenswert))"
                 r"|(kenntnis\w*|fließend\w*|verhandlungssicher\w*|fluent|proficien\w*|good|excellent|very good|sehr gut\w*|gut\w*)[^.\n]{0,30}(englisch|english)")


def english_of(text, lang):
    """Does the ad ask for English? An ad written in English implies it."""
    if lang == "EN":
        return "required"
    return "asked" if re.search(ENGLISH_ASKED, text, I) else "not mentioned"


MONTHS = r"jan\w*|feb\w*|m[aä]r\w*|apr\w*|ma[iy]|jun\w*|jul\w*|aug\w*|sep\w*|o[ck]t\w*|nov\w*|de[cz]\w*"


def _first(rx, text, fmt=lambda m: m.group(0)):
    m = re.search(rx, text, I)
    return fmt(m).strip() if m else ""


def details(text):
    return {
        "work_mode": ("Remote" if re.search(r"fully remote|100 ?% remote|remote[- ]first|vollständig remote", text, I) else
                      "Hybrid" if re.search(r"hybrid|remote|home ?office|mobile[ns]? arbeiten|mobile work", text, I) else ""),
        "hours": _first(r"(\d{1,2})\s*(?:[-–]|to|bis)?\s*(\d{1,2})?\s*(?:hours?|hrs|h|std\.?|stunden)\s*(?:per|a|/|pro|in der|each)\s*(?:week|woche)",
                        text, lambda m: f"{m.group(1)}{'–' + m.group(2) if m.group(2) else ''} h/week"),
        "start": _first(rf"(?:start\w*|beginn\w*|eintritt\w*|ab)\W{{1,3}}(?:date\W+|as of\W+|from\W+|on\W+)?"
                        rf"(asap|as soon as possible|immediately|ab sofort|sofort|\d{{1,2}}\.\d{{1,2}}\.\d{{2,4}}|(?:{MONTHS})\.? \d{{4}})",
                        text, lambda m: m.group(1)),
        "duration": _first(r"(\d{1,2})\s*(?:[-–]|to|bis)?\s*(\d{1,2})?\s*(?:months|monate)", text,
                           lambda m: f"{m.group(1)}{'–' + m.group(2) if m.group(2) else ''} months"),
        "pay": _first(r"(?:€|eur)\s?\d{2}(?:[.,]\d{1,2})?\s*(?:/|per|pro)\s*(?:h\b|hour|stunde)"
                      r"|\d{2}(?:[.,]\d{1,2})?\s*(?:€|eur\w*)\s*(?:/|per|pro|brutto pro)\s*(?:h\b|hour|stunde)", text),
        "mandatory": bool(re.search(r"mandatory internship|compulsory internship|pflichtpraktikum|curricular internship", text, I)),
    }
