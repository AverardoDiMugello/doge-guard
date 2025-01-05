import datetime
import json
import lxml.etree as ET
import os
from pathlib import Path
import re
import requests
import toml

ECFR_DATE = "2024-12-30"

# [EDITION] FR [PAGE NUMBER], [MONTH-ABBREV], [DATE], [YEAR]{, as ammended at [EDITION] FR [PAGE NUMBER], [MONTH-ABBREV], [DATE], [YEAR]{..}}
pattern = r"([0-9]+ FR [0-9]+, (Jan.|Feb.|Mar.|Apr.|May|June|July|Aug.|Sept.|Oct.|Nov.|Dec.) [0-9]{1,2}, [0-9]{4})"
citation_regex = re.compile(pattern)

def llm_analysis(fr_doc_data):
    pass


def citation_in_doc(cita_in_cfr, rule):
    fr_cita, fr_start, fr_stop = rule["citation"], rule["start_page"], rule["end_page"]
    cita_in_cfr = cita_in_cfr.split(" ")
    assert len(cita_in_cfr) == 3 and cita_in_cfr[1] == "FR"
    
    fr_cita = fr_cita.split(" ")
    assert len(fr_cita) == 3 and fr_cita[1] == "FR"
    
    assert int(fr_cita[2]) == fr_start
    same_edition = fr_cita[0] == cita_in_cfr[0]
    in_page_range = fr_start <= int(cita_in_cfr[2]) and int(cita_in_cfr[2]) <= fr_stop
    return same_edition and in_page_range


def parts_of_title(num, datadir):
    '''
    Fetch the structure of a CFR Title from the eCFR, cache it, and return a list of the component Parts.
    All CFR Titles are divided into Parts, unlike some other subdivisions (Chapter, Subchapter, etc.).
    '''
    structure_path = os.path.join(datadir, "cfr", f"title-{num}", "structure.json")
    try:
        with open(structure_path, "r") as f:
            structure = json.load(f)
    except FileNotFoundError:
        structure = requests.get(f"https://www.ecfr.gov/api/versioner/v1/structure/{ECFR_DATE}/title-{num}.json")
        structure.raise_for_status()
        structure = structure.json()
        with open(structure_path, "w") as f:
            json.dump(structure, f)

    def flatten_structure(item):
        flat_structure = [item]
        for child in item.get("children", []):
            flat_structure.extend(flatten_structure(child))
        return flat_structure
    
    return list(filter(lambda item : item["type"] == "part", flatten_structure(structure)))


def citations_of_part(titleno, partno, datadir):
    '''
    Fetch the full text of a CFR Part from the eCFR (XML format), cache it, then extract via regex any
    citations of the Federal Register along with whatever division of the CFR to which the citation belongs.
    Returns a dictionary {FR citation : [CFR Division]}, in which FR citation is a page citation string of  
    the form "X FR Y, Month, Date, Year" and CFR division is a tuple of the form ("NAME", "DIV-TYPE")
    '''
    part_path = os.path.join(datadir, "cfr", f"title-{titleno}", f"part-{partno}", "part.xml")
    try:
        with open(part_path, "r") as f:
            full_xml = ET.parse(f)
    except FileNotFoundError:
        full_xml = requests.get(f"https://www.ecfr.gov/api/versioner/v1/full/{ECFR_DATE}/title-{titleno}.xml?part={partno}")
        full_xml.raise_for_status()
        full_xml = full_xml.content
        with open(part_path, "wb") as f:
            f.write(full_xml)
        full_xml = ET.fromstring(full_xml)

    fr_cita_to_cfr_divs = {}

    for cita_elem in full_xml.iter("CITA"):
        div = cita_elem.getparent()
        divname, divty = div.attrib["N"], div.attrib["TYPE"]
        # Probably because my citation_regex is bad, a citation comes back to us in the form ('77 FR 46290, Aug. 3, 2012', 'Aug.'), so here
        # we turn it into just '77 FR 46290, Aug. 3, 2012'
        fr_citations = set(map(lambda c : c[0], re.findall(citation_regex, cita_elem.text)))
        
        for fr_cita in fr_citations:
            if fr_cita not in fr_cita_to_cfr_divs:
                fr_cita_to_cfr_divs[fr_cita] = set()
            fr_cita_to_cfr_divs[fr_cita].add((divname, divty))
        
    # This should just be accounted for in the sub-part granule citations
    # TODO: when we get CFR data that's better for time differentials, we can update this and test this hypothesis.
    # sources = full_xml.find("SOURCE")
    # if sources is not None:
    #     assert sources.find("HED").text == "Source:" and "Unexpected structure for the Source tag"
    #     citations.extend(re.findall(citation_regex, sources.find("PSPACE").text))

    return fr_cita_to_cfr_divs


def final_rules_for_part(titleno, partno, datadir):
    '''
    Search FederalRegister.gov for all Final Rule documents since 2000 that were marked as affecting the given CFR Part.
    Cache the search results. FR.gov's search API returns a JSON object, returned from this function as a dictionary.
    '''
    rule_search_path = os.path.join(datadir, "cfr", f"title-{titleno}", f"part-{partno}", "rules.json")
    try:
        with open(rule_search_path, "r") as f:
            rule_search = json.load(f)
    except FileNotFoundError:
        rule_query = "https://www.federalregister.gov/api/v1/documents.json"
        rule_query += "?per_page=1000&order=newest"
        rule_query += f"&conditions[cfr][title]={titleno}"
        rule_query += f"&conditions[cfr][part]={partno}"
        rule_query += "&conditions[publication_date][gte]=2000-01-01"
        rule_query += "&conditions[type][]=RULE"
        rule_query += "&fields[]=abstract"
        rule_query += "&fields[]=agencies"
        rule_query += "&fields[]=agency_names"
        rule_query += "&fields[]=body_html_url"
        rule_query += "&fields[]=cfr_references"
        rule_query += "&fields[]=citation"
        rule_query += "&fields[]=document_number"
        rule_query += "&fields[]=end_page"
        rule_query += "&fields[]=pdf_url"
        rule_query += "&fields[]=publication_date"
        rule_query += "&fields[]=significant"
        rule_query += "&fields[]=start_page"
        rule_query += "&fields[]=title"
        
        rule_search = requests.get(rule_query)
        rule_search.raise_for_status()
        rule_search = rule_search.json()
        
        total_pages = rule_search.get("total_pages", 0)
        if total_pages > 1:
            pageno = 2
            while pageno <= total_pages:
                rule_query += f"&page={pageno}"
                next_page = requests.get(rule_query)
                next_page.raise_for_status()
                next_page = next_page.json()
                rule_search["results"].extend(next_page["results"])
                pageno += 1
            
        with open(rule_search_path, "w") as f:
            json.dump(rule_search, f)
    
    return rule_search


def fetch_final_rules(final_rule_docs, datadir):
    '''
    Create the following portion of the database:
    final-rules/
        doc-no-X/
            details.toml
            index
            results.{txt, toml, json?}
            rule.html
            rule.pdf 
    '''
    # Needed for agency short name only. Can we get rid of this?
    all_agency_info = requests.get("https://www.federalregister.gov/api/v1/agencies")
    all_agency_info.raise_for_status()
    all_agency_info = all_agency_info.json()

    skipped = []
    num_rules = len(final_rule_docs)
    for i, docno in enumerate(final_rule_docs):
        print(f"{i+1}/{num_rules}: {docno}")
        rule_doc = final_rule_docs[docno][1]

        # Skip existing Final Rule docs
        document_dir = os.path.join(datadir, "final_rules", docno)
        if os.path.exists(document_dir):
            assert os.path.isdir(document_dir) and f"{document_dir} exists but isn't a directory."
            continue

        try:
            # Get the PDF of the rule
            pdf_res = requests.get(rule_doc["pdf_url"])
            pdf_res.raise_for_status()
            assert pdf_res.headers["Content-Type"].startswith("application/pdf")
            
            # Get the HTML and CFR Part of the rule
            html_res = requests.get(rule_doc["body_html_url"])
            html_res.raise_for_status()
            assert html_res.headers["Content-Type"].startswith("text/html")

            # Get the short-hand for each agency
            agency_names = []
            agency_abbrvs = []
            for agency in rule_doc["agency_names"]:
                try:
                    agency_abbrvs.append(next(agency_info["short_name"] for agency_info in all_agency_info if agency == agency_info["name"]))
                    agency_names.append(agency)
                except Exception as e:
                    continue

            details = {}
            details["title"] = rule_doc["title"]
            details["agencies"] = agency_names
            details["agency-shorthand"] = agency_abbrvs
            details["abstract"] = rule_doc["abstract"]
            details["citation"] = rule_doc["citation"]
            details["cfr-references"] = rule_doc["cfr_references"]
            date = rule_doc["publication_date"].split("-")
            details["publication-date"] = datetime.date(int(date[0]), int(date[1]), int(date[2]))
        except Exception as e:
            skipped.append((i, rule_doc, e))
            continue

        os.makedirs(document_dir, exist_ok=True)

        details_toml = os.path.join(document_dir, "details.toml")
        with open(details_toml, "w") as details_toml:
            toml.dump(details, details_toml)

        rule_pdf = os.path.join(document_dir, "rule.pdf")
        with open(rule_pdf, "wb") as rule_pdf:
            rule_pdf.write(pdf_res.content)

        rule_html = os.path.join(document_dir, "rule.html")
        with open(rule_html, "wb") as rule_html:
            rule_html.write(html_res.content)
    
    print(f"Total rules queried: {num_rules}")
    print(f"Total skipped: {len(skipped)}")
    return skipped


def cfr_to_fr_docs(titlenos, datadir):
    '''
    Create a database in the local filesystem with this structure:
    cfr-{date}/
        title-{titleno}/
            part-{X}/
                text.xml
                rules.json
            part-{Y}/
                ...
            ...
            structure.json
    final-rules/
        doc-no-X/
            details.toml
            index
            results.{txt, toml, json?}
            rule.html
            rule.pdf
        doc-no-Y/
            ...
        ...
    Return the FR doc data
    '''
    # fr_doc_data = {
    #     "fr-docno": [],
    #     "cfr-divs": [],
    #     "fr-citation": [], 
    #     "fr-doc-title": [],
    #     "fr-doc-agencies": [], 
    #     "fr-doc-agency-shorthand": [],
    #     "fr-doc-abstract": [],
    #     "fr-doc-publication-date": [], 
    #     "fr-doc-cfr-references": [], 
    #     "fr-doc-word-count": []
    # }
    final_rule_docs = {}
    # FR citations from the CFR that can't be mapped back to a Final Rule from FederalRegister.gov
    unaccounted_for_fr_citas = set()

    # TODO: update this when input language is improved
    for titleno in titlenos:
        os.makedirs(os.path.join(datadir, "cfr", f"title-{titleno}"), exist_ok=True)
        parts = parts_of_title(titleno, datadir)
        for part in parts:
            if not part["reserved"]:
                partno = part["identifier"] # Can be non-integer
                os.makedirs(os.path.join(datadir, "cfr", f"title-{titleno}", f"part-{partno}"), exist_ok=True)
                fr_cita_to_cfr_divs = citations_of_part(titleno, partno, datadir)
                final_rules = final_rules_for_part(titleno, partno, datadir)

                # Map each FR citation to its FR Final Rule document
                for fr_cita_with_date in fr_cita_to_cfr_divs:
                    fr_cita = fr_cita_with_date.split(",", 1)[0]
                    final_rule_identified = False
                    for rule in final_rules.get("results", []):
                        if citation_in_doc(fr_cita, rule):
                            docno = rule["document_number"]
                            if docno not in final_rule_docs:
                                final_rule_docs[docno] = (set(), rule)
                            # Aggregate the CFR divs that correspond to a single Final Rule
                            final_rule_docs[docno][0].update(fr_cita_to_cfr_divs[fr_cita_with_date])
                            final_rule_identified = True
                            
                    if not final_rule_identified:
                        # TODO: we should have some sense of why an FR citation was skipped
                        unaccounted_for_fr_citas.add(fr_cita)
            
    skipped = fetch_final_rules(final_rule_docs)
    return final_rule_docs, skipped
    

def check_title(titleno):
    try:
        titleno = int(titleno)
        assert 1 <= titleno and titleno <= 50
        assert titleno != 35 # Reserved
    except Exception:
        raise ValueError(f"{titleno} is not a valid CFR Title")


if __name__ == "__main__":
    '''
    Final output:
    Final rule docno, [CFR divs affected], Final rule meta..., LLM analysis

    User + Input:
        a team of legal and policy experts for a given agency select the Titles and/or Parts of the CFR they have jurisdiction over.
    Algo:
        cfr_to_fr_docs:
            Output: fsdb of Final Rules, fsdb of the CFR Parts, mem dictionary of FR2 docnos, CFR divs affected, and other data, maybe
            some output files describing the results, e.g. skipped
            1. Loads one or more CFR titles (eCFR)
            2. Divides it into Parts and fetches the XML of those Parts (eCFR)
            3. Aggregates the FR citations for each Part (eCFR)
            4. Aggregates and fetches all FR Final Rules since 2000 that affected each Part (FR.gov)
            5. Converts the previous two results into the set of Final Rule documents that compose all Parts in the Title
            6. Unite those results across all input Titles
        llm_analysis:
            Input: mem dictionary of data
            Output: input + LLM results as a .csv
            1. Statutory question
            2. Possibly a follow-up
    Output:

    '''
    import argparse
    parser = argparse.ArgumentParser("")
    parser.add_argument("data", help="The directory to store the results and analyzed data")
    parser.add_argument("--title", nargs='+', help="A CFR Title to analyze")
    # TODO: support more granulary ways of selecting CFR Parts to analyze
    # e.g. individual Parts, Part ranges, maybe entire chapters or sub-chapters
    
    args = parser.parse_args()

    # TODO: expand checks as input language expands
    cfr_inputs = []
    for titleno in args.title:
        check_title(titleno)
        cfr_inputs.append(titleno)

    # TODO: status?
    fr_doc_data, _ = cfr_to_fr_docs(cfr_inputs)
    fr_doc_analysis = llm_analysis(fr_doc_data)

    # TODO: save
