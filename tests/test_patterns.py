from __future__ import annotations

import pytest

from src.scraping import patterns


@pytest.mark.parametrize("text", [
    "Senior LLM Engineer, remote",
    "Ищем ML инженера в команду",
    "Data Scientist (Middle+)",
    "MLOps Engineer, Berlin",
    "Вакансия: инженер по машинному обучению",
    "Head of AI",
])
def test_relevant_titles(text):
    assert patterns.is_relevant(text)


@pytest.mark.parametrize("text", [
    "Golang backend developer, Postgres, Kafka",
    "Ищем менеджера по продажам",
    "Продаём курсы по фотографии",
])
def test_irrelevant_titles(text):
    assert not patterns.is_relevant(text)


def test_promo_is_not_a_vacancy():
    assert patterns.is_promo("Открытый урок по ML: записаться бесплатно. erid=2Vfn")
    assert patterns.parse_all("Открытый урок по ML для ML инженеров, erid=2Vfn") == []


def test_candidate_post_is_dropped():
    text = "#cv Ищу работу ML Engineer, 3 года опыта, remote"
    assert patterns.is_candidate_post(text)
    assert patterns.parse_all(text) == []


def test_qa_role_with_ai_mention_is_dropped():
    assert patterns.parse_all("QA Engineer (AI team), Москва, офис") == []


def test_salary_extracted_but_funding_is_not():
    assert patterns.extract_salary("Зарплата: 250 000 руб.") is not None
    assert patterns.extract_salary("ЗП: $5000 - $7000 gross") is not None
    assert patterns.extract_salary("Компания привлекла инвестиции $300 млн") is None


def test_negotiable_salary():
    assert patterns.extract_salary("Salary: negotiable") is not None


def test_location_and_remote_flag():
    loc, remote = patterns.extract_location("Локация: Remote (EU)")
    assert remote is True
    assert loc and "Remote" in loc

    loc, remote = patterns.extract_location("Локация: Москва, офис")
    assert remote is False
    assert loc == "Москва, офис"


def test_contact_prefers_the_apply_line():
    text = "ML Engineer\nО компании: t.me/some_company_news\nОтклики: @hr_anna"
    assert patterns.extract_contact(text) == "@hr_anna"
    assert patterns.extract_contact("ML Engineer. Резюме на jobs@acme.io") == "jobs@acme.io"


def test_single_post_yields_one_vacancy():
    vacs = patterns.parse_all("Senior LLM Engineer, remote, $150k/year, пишите @hr_bob")
    assert len(vacs) == 1
    assert vacs[0].remote is True
    assert vacs[0].contact == "@hr_bob"


def test_numbered_digest_splits_into_several():
    text = (
        "Подборка вакансий недели\n"
        "1) ML Engineer в Acme, Москва, отклик @hr_one\n"
        "2) Data Scientist в Globex, remote, отклик @hr_two\n"
    )
    vacs = patterns.parse_all(text)
    assert len(vacs) == 2
    assert {v.contact for v in vacs} == {"@hr_one", "@hr_two"}


def test_channel_footer_is_not_a_vacancy():
    text = (
        "1) ML Engineer в Acme, Москва, отклик @hr_one\n"
        "2) Data Scientist в Globex, remote, отклик @hr_two\n"
        "Больше вакансий в нашем канале @somechannel\n"
    )
    assert len(patterns.parse_all(text)) == 2


def test_parse_returns_first_vacancy_or_none():
    assert patterns.parse("Ничего интересного") is None
    assert patterns.parse("ML Engineer, remote").title


def test_as_dict_exposes_every_field():
    vac = patterns.parse("Senior ML Engineer, remote")
    assert set(patterns.as_dict(vac)) == {
        "title", "company", "salary", "location", "remote", "contact",
    }
