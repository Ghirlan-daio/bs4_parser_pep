import logging
import re
from collections import Counter
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL, PEP_URL
from outputs import control_output
from utils import find_tag, get_response


def whats_new(session):
    """
    Парсит ссылки на статьи о нововведениях в Python,
    переходит по ним и забирает информацию об авторах и редакторах статей.
    """
    whats_new_url = urljoin(MAIN_DOC_URL, "whatsnew/")
    response = get_response(session, whats_new_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features="lxml")
    main_div = find_tag(soup, "section", attrs={"id": "what-s-new-in-python"})
    div_with_ul = find_tag(main_div, "div", attrs={"class": "toctree-wrapper"})
    sections_by_python = div_with_ul.find_all(
        "li", attrs={"class": "toctree-l1"}
    )
    result = [("Ссылка на статью", "Заголовок", "Редактор, Автор")]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, "a")
        version_link = urljoin(whats_new_url, version_a_tag["href"])
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        h1 = find_tag(soup, "h1")
        dl = find_tag(soup, "dl")
        dl_text = dl.text.replace("\n", " ")
        result.append(
            (version_link, h1.text, dl_text)
        )
    return result


def latest_versions(session):
    """
    Парсит данные обо всех версиях Python
    - номера, статусы и ссылки на документацию.
    """
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features="lxml")

    sidebar = find_tag(soup, "div", attrs={"class": "sphinxsidebarwrapper"})

    ul_tags = sidebar.find_all("ul")
    for ul in ul_tags:
        if "All versions" in ul.text:
            a_tags = ul.find_all("a")
            break
    else:
        raise Exception("Ничего не нашлось")

    results = [("Ссылка на документацию", "Версия", "Статус")]
    pattern = r"Python (?P<version>\d\.\d+) \((?P<status>.*)\)"
    for a_tag in a_tags:
        link = a_tag["href"]
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ""
        results.append(
            (link, version, status)
        )
    return results


def download(session):
    """Скачивает архив с документацией Python на локальный диск."""
    downloads_url = urljoin(MAIN_DOC_URL, "download.html")
    response = get_response(session, downloads_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features="lxml")
    table_tag = find_tag(soup, "table", attrs={"class": "docutils"})
    pdf_a4_tag = find_tag(
        table_tag, "a", {"href": re.compile(r".+pdf-a4\.zip$")}
    )
    pdf_a4_link = pdf_a4_tag["href"]
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split("/")[-1]
    downloads_dir = BASE_DIR / "downloads"
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = get_response(session, archive_url)
    if response is None:
        return

    with open(archive_path, "wb") as file:
        file.write(response.content)
    logging.info(f"Архив был загружен и сохранён: {archive_path}")


def pep(session):
    """
    Парсит данные обо всех документах PEP.
    Сравнивает статус на странице PEP со статусом в общем списке.
    Считает количество PEP в каждом статусе и общее кол-во PEP.
    Сохраняет результаты в табличном виде в csv-файл.
    """
    response = get_response(session, PEP_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features="lxml")
    table_index = find_tag(soup, "section", {"id": "numerical-index"})
    tbody_tag = find_tag(table_index, "tbody")
    results = []
    table_tag = tbody_tag.find_all("td", string=re.compile(r"^\d+$"))

    for tag in tqdm(table_tag):
        a_tag = find_tag(tag, "a")
        pep_card_url = urljoin(PEP_URL, a_tag["href"])
        response = get_response(session, pep_card_url)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features="lxml")
        dl_tag = find_tag(soup, "dl", {"class": "rfc2822 field-list simple"})
        status_name = dl_tag.find(string="Status").parent
        status_pep_card = status_name.find_next_sibling("dd").text
        results.append(status_pep_card)

    total = 0
    counter = Counter(results)
    resulting_table = [("Status", "Quantity")]

    for status, count in counter.items():
        expected_statuses = [value for sublist in list(
            EXPECTED_STATUS.values()) for value in sublist]
        if status not in expected_statuses:
            logging.info(
                f"Статус не совпал:\n"
                f"Статус в карточке: {status}\n")
        else:
            resulting_table.append((status, count))
            total += count

    resulting_table.append(("Total", total))
    return resulting_table


"""Режимы работы парсера."""
MODE_TO_FUNCTION = {
    "whats-new": whats_new,
    "latest-versions": latest_versions,
    "download": download,
    "pep": pep,
}


def main():
    configure_logging()
    logging.info("Парсер запущен!")

    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f"Аргументы командной строки: {args}")

    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results is not None:
        control_output(results, args)
    logging.info("Парсер завершил работу.")


if __name__ == "__main__":
    main()
