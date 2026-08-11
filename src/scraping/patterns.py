from __future__ import annotations

import re
from dataclasses import dataclass, asdict

_DOMAIN = r"""(?:
      ml (?:[\s/\-]? ops)?
    | ai
    | llms?
    | nlp
    | gen (?:erative)? [\s\-]? ai
    | machine       [\s\-]* learning
    | deep          [\s\-]* learning
    | reinforcement [\s\-]* learning
    | artificial    [\s\-]* intelligence
    | large [\s\-]* language [\s\-]* models?
    | computer      [\s\-]* vision
    | machine       [\s\-]* vision
    | data          [\s\-]* science
    | машинн\w*        \s+ обучени\w*
    | машинному        \s+ обучению
    | глубок\w*        \s+ обучени\w*
    | искусственн\w*   \s+ интеллект\w*
    | больш\w* \s+ языков\w* \s+ модел\w*
    | языков\w*        \s+ модел\w*
    | нейросет\w*
    | нейронн\w*       \s+ сет\w*
    | (?<![А-Яа-яЁёA-Za-z]) ии (?![А-Яа-яЁёA-Za-z])
)"""

_ROLE = r"""(?:
      engineers?
    | researchers?
    | scientists?
    | developers?
    | \b dev \b
    | \b mle \b
    | инженер(?!и)\w*
    | разработчик\w*
    | исследовател\w*
    | специалист\w*
    | учён(?:ый|ого|ому|ым|ом|ые|ых|ыми)
    | учен(?:ый|ого|ому|ым|ом|ые|ых|ыми)
    | сайентист\w*
    | architect\w* | архитектор\w*
    | experts?\b | specialists?\b
    | тимлид\w* | руководител\w*
)"""

_SENIORITY = r"""(?:
      junior | middle | mid | senior | sr\.? | lead | staff | principal
    | head \s+ of | chief
    | джун\w* | мидл\w* | синьор\w* | сеньор\w* | ведущ\w* | главн\w*
    | старш\w* | руководител\w*
)"""

_STRONG_TITLE = r"""(?:
      \b mle \b
    | head \s+ of \s+ (?:ai|ml|llm|artificial|machine|data)
    | (?:ai|ml|llm) [\s/\-]+ (?:team[\s\-]?)? lead \b
    | (?:ai|ml|llm|genai) [\s\-/]+
      (?:product|platform|infra(?:structure)?|systems?|solutions?|applications?
         |research|applied|generative|full[\s\-]?stack|core|data|native)
      [\s\-]* (?:engineer|scientist)
    | data       \s* scientist
    | applied    \s* scientist
    | research   \s* scientist
    | research   \s* engineer
    | applied    \s* (?:ai|ml)? \s* engineer
    | ml \s* ops \s* engineer | mlops \s* engineer
    | prompt     \s* engineer
    | дата [\s\-]? сайентист\w*
    | ml  [\s\-]? инженер\w* | ai [\s\-]? инженер\w* | llm [\s\-]? инженер\w*
    | ml  [\s\-]? разработчик\w*
)"""

_CONNECT = r"(?:[\s,/\-]+(?:по|of|in|for|on|в|области)\b)?"

_FLAGS = re.IGNORECASE | re.VERBOSE | re.UNICODE

_ADJACENT = re.compile(
    rf"""(?:
          {_DOMAIN} [\s/\-–—]{{0,3}} {_ROLE}
        | {_ROLE} {_CONNECT} [\s,/\-(:]* {_DOMAIN}
    )""",
    _FLAGS,
)
_STRONG = re.compile(_STRONG_TITLE, _FLAGS)

_TITLE_SPAN = re.compile(
    rf"(?:{_SENIORITY}[\s\-]+)?(?:{_ADJACENT.pattern}|{_STRONG_TITLE})",
    _FLAGS,
)

_TITLE_LABEL = re.compile(
    r"""^[^\wА-Яа-яЁё\n]{0,8}
        (?:ваканси\w*|позици\w*|должност\w*|role|position|title|job\s*title)
        \s*[:\-–—]\s*(?P<v>.+)$""",
    _FLAGS | re.MULTILINE,
)
_COMPANY_LABEL = re.compile(
    r"""^\s*[*_>•\-\s]*
        (?:компани\w*|работодател\w*|company|employer|о\s+компании|about\s+us)
        \s*[:\-–—]\s*(?P<v>.+)$""",
    _FLAGS | re.MULTILINE,
)
_SALARY_LABEL = re.compile(
    r"""(?:зарплат\w*|з/?п|оклад|доход|вилк\w*|компенсаци\w*|бюджет|рейт|ставк\w*
        |salary|compensation|\bpay\b|budget|\brate\b|money)
        \s*[:\-–—]?\s*(?P<v>[^\n]+)""",
    _FLAGS,
)
_LOCATION_LABEL = re.compile(
    r"""(?:локаци\w*|город|местоположени\w*|формат\s+работ\w*|тип\s+занятост\w*
        |location|office|офис|где\s+работать|work\s*(?:type|format|location)
        |employment(?:\s*type)?)
        \s*[:\-–—]\s*(?P<v>[^\n]+)""",
    _FLAGS,
)

_CUR = r"(?:\$|€|£|₽|₴|₸|zł|руб\.?|р\.|usd|eur|gbp|rub|pln|uah|kzt|тенге|грн|тг)"
_AMOUNT = r"(?:\d{1,3}(?:[ .,  ]\d{3})+|\d+)(?:[.,]\d+)?\s*(?:k|к|тыс\.?|млн)?"
_PERIOD = (
    r"(?:\+?\s*(?:gross|net|на\s*руки|до\s*вычета|после\s*вычета"
    r"|/\s*(?:month|year|hour|mo|мес\.?|год|час)"
    r"|per\s*(?:month|year|hour)|в\s*(?:месяц|год|час)|к\s*выплате))?"
)
_SALARY_CUR = re.compile(
    rf"""(?:от\s*|from\s*)?
        (?:
              {_CUR}\s*{_AMOUNT}(?:\s*[-–—]\s*(?:{_CUR}\s*)?{_AMOUNT})?
            | {_AMOUNT}(?:\s*[-–—]\s*{_AMOUNT})?\s*{_CUR}
        )
        \s*{_CUR}? \s*{_PERIOD}""",
    _FLAGS,
)
_SALARY_NEGOTIABLE = re.compile(
    r"""(?:по\s+договор\w*|договорн\w*|negotiable|discussed\s+individually
        |competitive|конкурентн\w*|по\s+результатам\s+собеседовани\w*
        |by\s+agreement|обсуждается(?:\s+индивидуально)?)""",
    _FLAGS,
)
_INVEST = re.compile(
    r"""(?:инвестиц|привлек|раунд|\bround\b|\braised?\b|\bseed\b|series\s*[a-e]\b
        |венчур|valuation|оцен(?:ка|ен|ил)\w*|под\s+управлени|\bAUM\b
        |assets\s+under|финансировани|капитализац|годов\w*\s+оборот|выручк
        |размер\s+команд|team\s+size|funding)""",
    _FLAGS,
)
_MAGNITUDE_BIG = re.compile(r"^\s*(?:M\b|B\b|млн|млрд|million|billion|kk)", re.IGNORECASE)

_PROMO = re.compile(
    r"""(?:
          \b erid \s* =
        | открыт\w* \s+ урок
        | (?:бесплатн\w*|приглашаем\s+на|записаться\s+на|регистрац\w*\s+на|запишись\s+на)
          \s+ (?:вебинар|курс|интенсив|урок|мастер[\s\-]?класс|воркшоп|workshop|митап|бут\s?камп)
        | участвовать \s+ бесплатно
        | otus | skillbox | нетологи | geekbrains | яндекс[\s\-]?практикум | karpov
        | демо[\s\-]?день \s+ курса
        | вечеринк\w* | нетворкинг\w* | after[\s\-]?party | meetup | митап\w*
        | \#ads\b | \#реклама\b | \#промо\b
    )""",
    _FLAGS,
)

_NUM_ITEM = re.compile(r"(?m)^\s*\d{1,2}[\).]\s+(?=\S)")
_SEP_LINE = re.compile(r"(?m)^[ \t]*[─—–\-=_•·*~>#]{3,}[ \t]*$")
_DIGEST = re.compile(r"дайджест|digest|подборк\w*\s+вакансий", re.IGNORECASE)
_DETAIL = re.compile(
    r"""(?:/|@|\bв\s+[«"A-ZА-ЯЁ]|\bat\s+[A-Z]|remote|удал[её]|hybrid|гибрид
        |apply|отклик|relocation|релокац|\$|€|₽|руб|zł|локац|location|город
        |компани|company|vacancy|ваканси)""",
    _FLAGS,
)
_SEG_JUNK = re.compile(
    r"(?:job\s*alert|_bot\b|@\w+bot\b|узнать\s+(?:подроб|детал|больше)"
    r"|(?:друг\w*|ещ[её]\s+больше|больше|полн\w*\s+список)\s+вакан"
    r"|other\s+vacanc|100%\s*free|в\s+наш\w*\s+(?:канал|тг|телеграм))",
    _FLAGS,
)

_REMOTE = r"(?:full[\s\-]?)?remote|удал[её]нк\w*|удал[её]нн\w*|дистанционн\w*|from\s+anywhere|worldwide|wfh"
_HYBRID = r"hybrid|гибрид\w*"
_ONSITE = r"on[\s\-]?site|in[\s\-]?office|офис\w*"
_RELOC = r"relocation|релокац\w*|переезд|relocate"
_LOC_KEYWORDS = re.compile(rf"(?P<kw>{_REMOTE}|{_HYBRID}|{_ONSITE}|{_RELOC})", _FLAGS)

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TG_HANDLE = re.compile(r"@[A-Za-z][A-Za-z0-9_]{4,31}")
_TG_LINK = re.compile(r"(?:https?://)?t\.me/(?!c/|joinchat|\+)([A-Za-z][A-Za-z0-9_]{4,31})")
_CONTACT_CTX = re.compile(
    r"(контакт|связ|пиш|писать|напис|откл|резюме|\bcv\b|apply|contact|reach"
    r"|\bdm\b|по\s+вопрос|\bhr\b|телеграм|\btg\b|for\s+details|send|отправ)",
    _FLAGS,
)

_CANDIDATE = re.compile(
    r"""(?:
          \#cv\b | \#resume\b | \#opentowork | \#ищуработу | \#готовработать
        | рассматриваю \s+ предложени
        | ищу \s+ (?:работу|вакансию|проект|позици|команду)
        | в \s+ поиск\w* \s+ (?:работы|новой\s+работы|проекта)
        | open \s+ to \s+ work
        | ищу \s+ (?:удал[её]нн\w*|remote)
        | резюме \s+ (?:кандидат|специалист)
        | looking \s+ for \s+ (?:an?\s+)? (?:internship|junior|position|job|role|opportunit\w*|work)
        | seeking \s+ (?:an?\s+)? (?:position|role|internship|job|opportunit\w*)
    )""",
    _FLAGS,
)

_NEGATIVE_TITLE = re.compile(
    r"""\b(?:
          a?qa \s* engineer | qa \s* automation | automation \s* qa | sdet
        | тестировщик\w* | автоматизатор\w* \s* тестир
        | (?:marketing|sales|account|affiliate|community|office|bonus|hr)
          \s* manager
        | менеджер \s+ по \s+ (?:продаж|маркетинг|персонал)
    )\b""",
    _FLAGS,
)

_MD = re.compile(r"[*_`~]+")
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff←-⇿⬀-⯿️]"
)
_HASHTAG = re.compile(r"#\w+", re.UNICODE)
_WS = re.compile(r"[ \t ]+")


def _clean(s: str) -> str:
    s = _MD.sub("", s)
    s = _EMOJI.sub("", s)
    s = s.strip(" \t\r\n-–—•*:>|·").strip()
    s = _WS.sub(" ", s)
    return s


def _strip_tags(s: str) -> str:
    return _clean(_HASHTAG.sub(" ", s))


@dataclass
class Vacancy:
    title: str | None = None
    company: str | None = None
    salary: str | None = None
    location: str | None = None
    remote: bool = False
    contact: str | None = None


def is_relevant(text: str) -> bool:
    text = _HASHTAG.sub(" ", text)
    return bool(_ADJACENT.search(text) or _STRONG.search(text))


def is_candidate_post(text: str) -> bool:
    return bool(_CANDIDATE.search(text))


def is_promo(text: str) -> bool:
    return bool(_PROMO.search(text))


def extract_title(text: str) -> str | None:
    m = _TITLE_LABEL.search(text)
    if m:
        v = _strip_tags(m.group("v"))
        if 2 < len(v) <= 120:
            return v

    for raw in text.splitlines()[:6]:
        line = _strip_tags(raw)
        if 3 <= len(line) <= 90 and is_relevant(line):
            return line

    m = _TITLE_SPAN.search(text) or _ADJACENT.search(text) or _STRONG.search(text)
    if not m:
        return None
    return _clean(m.group(0)) or None


def extract_company(text: str) -> str | None:
    m = _COMPANY_LABEL.search(text)
    if m:
        v = _clean(m.group("v"))
        if 1 < len(v) <= 80:
            return v
    return None


def _is_investment(s: str, m: re.Match) -> bool:
    if _INVEST.search(s[max(0, m.start() - 25): m.start()]):
        return True
    if _MAGNITUDE_BIG.match(s[m.end(): m.end() + 10]):
        return True
    if re.search(r"млн|млрд|million|billion|\bkk\b|\bb\b", m.group(0), re.IGNORECASE):
        return True
    return False


def _salary_from(s: str) -> str | None:
    for m in _SALARY_CUR.finditer(s):
        if _is_investment(s, m):
            continue
        return _clean(m.group(0))
    return None


def extract_salary(text: str) -> str | None:
    m = _SALARY_LABEL.search(text)
    if m:
        seg = m.group("v")
        val = _salary_from(seg)
        if val:
            return val
        if _SALARY_NEGOTIABLE.search(seg):
            return _clean(seg)[:60]
    val = _salary_from(text)
    if val:
        return val
    neg = _SALARY_NEGOTIABLE.search(text)
    if neg:
        return _clean(neg.group(0)).capitalize()
    return None


def extract_location(text: str) -> tuple[str | None, bool]:
    remote = bool(re.search(_REMOTE, text, _FLAGS))

    m = _LOCATION_LABEL.search(text)
    if m:
        v = _clean(m.group("v"))
        if 1 < len(v) <= 90:
            return v, remote or bool(re.search(_REMOTE, v, _FLAGS))

    m = _LOC_KEYWORDS.search(text)
    if m:
        kw = _clean(m.group("kw"))
        tail = text[m.end() : m.end() + 70]
        paren = re.match(r"\s*\(([^)]{1,60})\)", tail)
        if paren:
            return _clean(f"{kw} ({paren.group(1)})"), remote
        place = re.match(r"\s*[,\-–—]?\s*([A-ZА-ЯЁ][\w .,/&+'()–-]{1,45})", tail)
        if place:
            cand = _clean(place.group(1))
            cand = re.split(r"\s{2,}|[.;•]|\bна\b|\bwith\b", cand)[0].strip()
            if cand and not re.match(
                r"локац|город|location|зарплат|salary|контакт|contact|формат|занятост",
                cand, _FLAGS,
            ):
                return _clean(f"{kw} {cand}"), remote
        return kw.capitalize(), remote

    return None, remote


def _find_contact_token(segment: str) -> str | None:
    m = _EMAIL.search(segment)
    if m:
        return m.group(0)
    m = _TG_LINK.search(segment)
    if m:
        return "@" + m.group(1)
    m = _TG_HANDLE.search(segment)
    if m:
        return m.group(0)
    return None


def extract_contact(text: str) -> str | None:
    for km in _CONTACT_CTX.finditer(text):
        tok = _find_contact_token(text[km.start() : km.start() + 90])
        if tok:
            return tok
    return _find_contact_token(text)


def _prep_segment(seg: str) -> str | None:
    seg = seg.strip()
    lines = seg.splitlines()
    cut = next((i for i, ln in enumerate(lines) if _SEG_JUNK.search(ln)), None)
    if cut is not None:
        seg = "\n".join(lines[:cut]).strip()
    if len(_HASHTAG.sub(" ", seg).strip()) < 10:
        return None
    ok = (
        is_relevant(seg)
        and _DETAIL.search(seg)
        and not is_candidate_post(seg)
        and not is_promo(seg)
    )
    return seg if ok else None


def split_vacancies(text: str) -> list[str]:
    if len(_NUM_ITEM.findall(text)) >= 2:
        parts = _NUM_ITEM.split(text)[1:]
    elif _DIGEST.search(text):
        parts = re.split(r"\n[ \t]*\n", text)
    elif len(_SEP_LINE.findall(text)) >= 2:
        parts = _SEP_LINE.split(text)
    else:
        return [text]
    good = [s for s in (_prep_segment(p) for p in parts) if s]
    return good if good else [text]


def _build_vacancy(text: str) -> Vacancy | None:
    if not is_relevant(text) or is_candidate_post(text) or is_promo(text):
        return None
    title = extract_title(text)
    if title and _NEGATIVE_TITLE.search(title):
        return None
    loc, remote = extract_location(text)
    return Vacancy(
        title=title,
        company=extract_company(text),
        salary=extract_salary(text),
        location=loc,
        remote=remote,
        contact=extract_contact(text),
    )


def _strip_junk_lines(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not _SEG_JUNK.search(ln))


def parse_all(text: str) -> list[Vacancy]:
    if not text or is_candidate_post(text) or is_promo(text):
        return []
    text = _strip_junk_lines(text)
    if not is_relevant(text):
        return []
    out: list[Vacancy] = []
    seen: set[str] = set()
    for seg in split_vacancies(text):
        v = _build_vacancy(seg)
        if not v:
            continue
        key = (v.title or "").strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def parse(text: str) -> Vacancy | None:
    vacancies = parse_all(text)
    return vacancies[0] if vacancies else None


def as_dict(v: Vacancy) -> dict:
    return asdict(v)
