import csv
import json

from openpyxl import load_workbook

from hhfinder.exporters import export_vacancies
from hhfinder.models import Vacancy


def sample() -> Vacancy:
    return Vacancy(
        id="1", source="hh_web", title="IT-специалист", company="Компания",
        salary_from=50000, currency="RUR", salary_display="от 50 000 ₽",
        no_salary=False, city="Набережные Челны", experience="Без опыта",
        experience_id="noExperience", category="IT и техподдержка",
        score=72, score_explanation="Совпали навыки: Linux, Python",
        score_factors={"skills": 12, "salary": 8}, published_at="2026-11-01T10:00:00+03:00",
        url="https://hh.ru/vacancy/1", is_new=True, enriched=True,
        description="Настройка рабочих мест и сетей",
    )


def test_csv_json_xlsx_export(tmp_path):
    items = [sample()]
    csv_path = export_vacancies(items, tmp_path / "jobs.csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert len(rows) == 1 and rows[0]["Должность"] == "IT-специалист"

    json_path = export_vacancies(items, tmp_path / "jobs.json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["vacancies"][0]["ID вакансии"] == "1"

    xlsx_path = export_vacancies(items, tmp_path / "jobs.xlsx")
    workbook = load_workbook(xlsx_path)
    assert "Вакансии" in workbook.sheetnames
    assert workbook["Вакансии"].max_row == 2
    assert "Сводка" in workbook.sheetnames
