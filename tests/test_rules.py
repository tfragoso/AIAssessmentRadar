import pytest

from jobwatch.enrich import rules


@pytest.mark.parametrize(
    "title, level",
    [
        ("Senior Data Scientist", "senior"),
        ("Data Scientist", ""),
        ("Praktikum Data Science (80-100%)", "intern"),
        ("Stagiaire en science des données", "intern"),
        ("Head of Model Risk Management", "director"),
        ("Associate Director, Biostatistics", "director"),
        ("Senior Manager AI Governance", "lead"),
        ("Leiter/in Modellvalidierung", "lead"),
        ("Senior Associate - Model Validation", "senior"),
        ("Junior Statistiker (w/m/d)", "junior"),
        ("Postdoctoral researcher in trustworthy AI", "junior"),
        ("Principal Biostatistician", "lead"),
        ("Data Scientist confirmé(e)", "senior"),
    ],
)
def test_seniority(title, level):
    assert rules.seniority(title) == level


def test_seniority_falls_back_on_years():
    assert rules.seniority("Data Scientist", 6) == "senior"
    assert rules.seniority("Data Scientist", 3) == "mid"


@pytest.mark.parametrize(
    "text, years",
    [
        ("You have 5+ years of experience in model validation.", 5),
        ("At least 3 years' relevant professional experience", 3),
        ("3-5 years of experience in quantitative finance", 3),
        ("Minimum of two years of hands-on experience with Python", 2),
        ("Experience: at least 7 years in a similar role", 7),
        ("Mindestens 5 Jahre Berufserfahrung im Risikomanagement", 5),
        ("Sie verfügen über 3 Jahre Erfahrung in der Modellvalidierung", 3),
        ("Mehrjährige Erfahrung in Data Governance", None),
        ("5 ans d'expérience minimum dans un poste similaire", 5),
        ("Au moins trois années d'expérience en statistique", 3),
        ("We have been around for 150 years.", None),
        ("Founded 20 years ago, we offer a great experience", 20),  # known limitation, documents behaviour
    ],
)
def test_years(text, years):
    assert rules.years_required(text) == years


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Fluent in German and English; French is a plus.", "de:C1:required; fr:?:plus; en:C1:required"),
        ("Sehr gute Deutsch- und Englischkenntnisse, Französisch von Vorteil",
         "de:C1:required; fr:?:plus; en:C1:required"),
        ("Excellent English (C1) and German (B2) skills", "de:B2:required; en:C1:required"),
        ("Deutsch C1, Englisch B2", "de:C1:required; en:B2:required"),
        ("Français courant, anglais un atout", "fr:C1:required; en:?:plus"),
        ("Langue maternelle française, très bonnes connaissances de l'allemand",
         "de:B2:required; fr:C2:required"),
        ("Verhandlungssicheres Deutsch und gute Englischkenntnisse", "de:C1:required; en:B2:required"),
        ("Ideally you also speak Italian.", "it:?:plus"),
        ("We are an English-speaking team in an international environment", ""),
        ("Our office is in German-speaking Switzerland", ""),
    ],
)
def test_languages(text, expected):
    assert rules.languages_required(text) == expected


@pytest.mark.parametrize(
    "text, lang",
    [
        ("We are looking for a data scientist who will join our team and work with the latest models.", "en"),
        ("Wir suchen eine Persönlichkeit, die mit uns die Zukunft der Versicherung gestaltet und für die Kunden da ist.", "de"),
        ("Nous recherchons une personne motivée pour rejoindre notre équipe et pour développer des modèles.", "fr"),
    ],
)
def test_ad_language(text, lang):
    assert rules.ad_language(text) == lang


@pytest.mark.parametrize(
    "title, text, hint, expected",
    [
        ("Data Scientist", "This is a permanent position.", "", "permanent"),
        ("Data Scientist (befristet)", "", "", "fixed-term"),
        ("Statisticien", "Contrat à durée déterminée (CDD) de 12 mois", "", "fixed-term"),
        ("Model Validator", "This is a 12-month contract with possible extension.", "", "fixed-term"),
        ("Analyst (Contract through our external payroll partner, 12 months)", "", "", "temporary-agency"),
        ("Data Scientist", "Unbefristete Festanstellung", "", "permanent"),
        ("Data Scientist", "Probezeit von 3 Monaten", "", ""),
        ("Data Scientist", "", "Permanent", "permanent"),
    ],
)
def test_contract(title, text, hint, expected):
    assert rules.contract_type(title, text, hint) == expected


@pytest.mark.parametrize(
    "title, text, hint, expected",
    [
        ("Data Scientist 80-100%", "", "", "80-100%"),
        ("Data Scientist (80 - 100 %)", "", "", "80-100%"),
        ("Statistiker", "Pensum: 60 bis 80 %", "", "60-80%"),
        ("Data Scientist", "Taux d'activité : 100%", "", "100%"),
        ("Data Scientist", "Up to 20% travel", "", ""),
        ("Data Scientist", "100% remote possible", "", ""),
        ("Data Scientist", "", "Vollzeit", "100%"),
        ("Kundenberater", "", "50-100%", "50-100%"),
    ],
)
def test_workload(title, text, hint, expected):
    assert rules.workload(title, text, hint) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Salary range: CHF 120'000 - 150'000 per year", ("120000", "150000")),
        ("CHF 95,000 to CHF 110,000", ("95000", "110000")),
        ("120k-140k CHF", ("120000", "140000")),
        ("Budget CHF 5-10 million", ("", "")),
    ],
)
def test_salary(text, expected):
    assert rules.salary(text) == expected


def test_remote():
    assert rules.remote("x", "", "Hybrid") == "hybrid"
    assert rules.remote("x", "Fully remote within Switzerland", "") == "remote"
    assert rules.remote("x", "Möglichkeit für Homeoffice", "") == "hybrid"
    assert rules.remote("x", "Télétravail partiel possible", "") == "hybrid"
    assert rules.remote("x", "Nice office in Zurich", "") == ""
