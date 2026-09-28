"""Reference data: where postings come from and the vocabularies used to describe them."""

CITY = "Hamburg"
RADIUS_KM = 25

# Federal Employment Agency search terms covering student-level jobs in every field
BA_TERMS = [
    "Werkstudent", "Werkstudentin", "Working Student", "Studentische Aushilfe", "Studentische Hilfskraft",
    "Praktikum", "Praktikant", "Internship", "Intern", "Pflichtpraktikum",
    "Abschlussarbeit", "Bachelorarbeit", "Masterarbeit", "Thesis",
    "Trainee", "Junior", "Berufseinsteiger", "Graduate",
    "Student", "Studentenjob", "Studierende", "Praxissemester", "Volontariat", "Absolvent",
    # the agency's own "internship / trainee" category, whatever the title says (~200 extra ads, 2026-09-28)
    {"angebotsart": 34},
]

# company career feeds with Hamburg postings: (ats, slug, display name)
COMPANIES = [
    ("smartrecruiters", "aboutyougmbh", "ABOUT YOU"),
    ("smartrecruiters", "vattenfall", "Vattenfall"),
    ("greenhouse", "freenow", "FREENOW"),
    ("greenhouse", "moia", "MOIA"),
    ("greenhouse", "appinio", "Appinio"),
    ("greenhouse", "dept", "DEPT"),
    ("greenhouse", "sumup", "SumUp"),
    ("greenhouse", "hellofresh", "HelloFresh"),
    ("greenhouse", "raisin", "Raisin"),
    ("greenhouse", "scout24", "Scout24"),
    ("greenhouse", "mongodb", "MongoDB"),
    ("ashby", "statista", "Statista"),
    ("ashby", "enpal", "Enpal"),
    ("ashby", "thoughtworks", "Thoughtworks"),
    ("lever", "netlight", "Netlight"),
    ("personio", "1komma5grad", "1KOMMA5°"),
    ("personio", "bigpoint", "Bigpoint"),
    ("workday", "ag|wd3|Airbus", "Airbus"),
    ("workday", "unilever|wd3|Unilever_Experienced_Professionals", "Unilever"),
    # added 2026-09-27 after probing ~200 Hamburg employers across 7 ATS systems
    ("ashby", "adjoe", "adjoe"),
    ("personio", "metergrid", "metergrid"),
    ("personio", "snocks", "SNOCKS"),
    ("personio", "closed", "CLOSED"),
    ("greenhouse", "ogilvy", "Ogilvy"),
    ("personio", "infiniteroots", "infinite roots"),
    ("personio", "lemundo", "Lemundo"),
    ("personio", "natsana", "Natsana"),
    ("personio", "hvv", "hvv"),
    # added 2026-09-28: Workday career sites with Hamburg postings (found via search, probed live)
    ("workday", "philips|wd3|jobs-and-careers", "Philips"),
    ("workday", "nxp|wd3|careers", "NXP Semiconductors"),
    ("workday", "mabanaft|wd3|Mabanaft", "MB Energy"),
    ("workday", "shell|wd3|ShellCareers", "Shell"),
    ("workday", "db|wd3|DBWebsite", "Deutsche Bank"),
    ("workday", "cc|wd3|ChanelCareers", "CHANEL"),
]

# Adzuna (free plan: 250 calls/day, 2,500/month) - fewer, broader terms; each call returns up to 50 ads
ADZUNA_TERMS = ["werkstudent", "working student", "praktikum", "internship", "abschlussarbeit",
                "masterarbeit", "bachelorarbeit", "trainee", "studentenjob", "junior"]
ADZUNA_DAILY_CALLS = 70     # first run: full crawl within this; later runs only need ~10
ADZUNA_KEEP_DAYS = 45       # Adzuna ads are not re-checked daily, so they expire by age

# JSearch (free plan: 200 requests/month, hard limit) - one request per query per day, 6 x 31 = 186
JSEARCH_QUERIES = ["Werkstudent in Hamburg", "Praktikum in Hamburg", "working student in Hamburg",
                   "internship in Hamburg", "Abschlussarbeit in Hamburg", "Studentenjob in Hamburg"]
JSEARCH_DAILY_CALLS = 6
JSEARCH_KEEP_DAYS = 30      # like Adzuna: not re-checked daily, so they expire by age

LEVELS = ["Werkstudent", "Internship", "Thesis", "Student side job", "Junior / Trainee"]

FIELDS = [
    "Data & Analytics", "Software & IT", "Engineering", "Marketing & Communications", "Sales & Business Development",
    "Finance & Controlling", "HR & Recruiting", "Operations & Logistics", "Consulting & Strategy", "Product & Design",
    "Research & Science", "Healthcare & Social", "Legal", "Media & Content", "Other",
]

# title keyword -> field, first match wins (used when the AI step is off or failed)
FIELD_RULES = [
    ("Data & Analytics", r"data|daten|analyt|artificial intelligence|machine learning|business intelligence|\bbi\b|power ?bi|reporting|statisti"),
    ("Software & IT", r"software|developer|entwickl|\bit\b|it-|informatik|devops|cloud|frontend|backend|full ?stack|cyber|security|sap|web"),
    ("Finance & Controlling", r"finan|controlling|accounting|buchhalt|audit|tax|steuer|prüfung|kredit|payroll|lohn|treasury|bank|invest|risk"),
    ("Marketing & Communications", r"marketing|kommunikation|communication|social media|seo|brand|pr\b|public relations|content|e-?commerce"),
    ("Sales & Business Development", r"sales|vertrieb|business development|account|key account|kundenberat"),
    ("HR & Recruiting", r"\bhr\b|human resources|personal|recruit|talent|people"),
    ("Operations & Logistics", r"logisti|supply chain|einkauf|procurement|purchas|operations|lager|transport|shipping|office|assisten|assistant|customer service|kundenservice|backoffice"),
    ("Consulting & Strategy", r"consult|berat|strateg|m&a|transformation"),
    ("Product & Design", r"product|produkt|design|art direct|creative|kreativ|ux|ui\b|grafik"),
    ("Engineering", r"engineer|ingenieur|maschinenbau|mechani|elektro|electrical|konstruktion|produktion|production|quality|qualität|aircraft|aerospace|luftfahrt|bau\b|civil|technik"),
    ("Research & Science", r"research|forschung|wissenschaft|labor|lab\b|chemie|chemist|biolog|physik|physics"),
    ("Healthcare & Social", r"pflege|medizin|medical|health|gesundheit|sozial|social work|therap|kita|pädagog"),
    ("Legal", r"legal|recht|jurist|law\b|compliance|datenschutz"),
    ("Media & Content", r"redaktion|editor|journal|media|medien|video|film|foto|photo|podcast"),
]

# canonical skill label -> regex over title + description (case-insensitive unless in CASE_SENSITIVE)
SKILLS = {
    "Python": r"\bpython\b", "SQL": r"\bsql\b", "R": r"(?<![\w&])R(?![\w&'’.-])", "Java": r"java(?!script)\b",
    "JavaScript": r"javascript|\bjs\b", "TypeScript": r"typescript", "C++": r"c\+\+", "C#": r"c#|\.net\b",
    "Go": r"\bgolang\b", "React": r"\breact\b", "Node.js": r"node\.?js", "PHP": r"\bphp\b", "MATLAB": r"matlab",
    "Excel": r"\bexcel\b", "MS Office": r"ms office|microsoft office|office 365|m365|powerpoint",
    "Power BI": r"power ?bi", "Tableau": r"tableau", "SAP": r"\bsap\b", "Salesforce": r"salesforce",
    "Git": r"\bgit\b|github|gitlab", "Docker": r"docker", "Kubernetes": r"kubernetes|\bk8s\b",
    "AWS": r"\baws\b|amazon web services", "Azure": r"azure", "GCP": r"\bgcp\b|google cloud",
    "Machine learning": r"machine learning|\bml\b|deep learning", "AI / LLMs": r"\bllms?\b|generative ai|genai|chatgpt|copilot|\bki\b",
    "Statistics": r"statisti", "Data visualisation": r"visuali[sz]", "ETL": r"\betl\b|\belt\b",
    "Figma": r"figma", "Adobe CC": r"adobe|photoshop|illustrator|indesign|premiere", "SEO": r"\bseo\b|\bsea\b",
    "Google Analytics": r"google analytics|\bga4\b", "CAD": r"\bcad\b|catia|solidworks|autocad|siemens nx",
    "Jira": r"\bjira\b|confluence", "Agile / Scrum": r"agile|agil|scrum|kanban",
    "Project management": r"project management|projektmanagement|projektmanag",
}
CASE_SENSITIVE = {"R"}

GERMAN_REQUIRED = (r"(fluent|fließend|verhandlungssicher|sehr gut\w*|excellent|business[- ]fluent|proficien\w*)"
                   r"[^.\n]{0,40}(german|deutsch)|(german|deutsch)\w*[^.\n]{0,25}\b(c1|c2|fluent|fließend|native|mandatory|required)"
                   r"|deutschkenntnisse")
GERMAN_NICE = r"german[^.\n]{0,40}(plus|nice|advantage|bonus|beneficial|desirable)|(plus|advantage|nice)[^.\n]{0,30}german"
