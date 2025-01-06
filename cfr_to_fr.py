import datetime
import json
import lxml.etree as ET
import os
import pandas as pd
from pathlib import Path
import re
import requests
import toml

# TODO: use CFR date properly
ECFR_DATE = "2024-12-30"
CFR_TITLES = [str(num) for num in range(1, 51)]

# [EDITION] FR [PAGE NUMBER], [MONTH-ABBREV], [DATE], [YEAR]{, as ammended at [EDITION] FR [PAGE NUMBER], [MONTH-ABBREV], [DATE], [YEAR]{..}}
pattern = r"([0-9]+ FR [0-9]+, (Jan.|Feb.|Mar.|Apr.|May|June|July|Aug.|Sept.|Oct.|Nov.|Dec.) [0-9]{1,2}, [0-9]{4})"
citation_regex = re.compile(pattern)

def llm_analysis(fr_doc_data, datadir):
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

            details = {}
            details["title"] = rule_doc["title"]
            details["agencies"] = rule_doc["agencies"]
            details["agency-shorthand"] = rule_doc["agency-shorthand"]
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


def cfr_to_fr_docs(cfr_parts, datadir):
    '''
    Input: [(titleno, part)]
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
            index # Added by llm_analysis
            results.{txt, toml, json?} # Added by llm_analysis
            rule.html
            rule.pdf
        doc-no-Y/
            ...
        ...
    Return the FR doc data and status
    Right now, status is the FR docs that were cited but couldn't be fetched and the FR citations from the CFR that couldn't
    be attributed to a Final Rule doc at FederalRegister.gov
    '''
    # FR document numbers to a tuple of the relevant FR doc info from FederalRegister.gov and the set of CFR divisions in which the FR doc was cited
    fr_docs_in_cfr = {}
    # FR citations from the CFR that can't be mapped back to a document from FederalRegister.gov
    unaccounted_for_fr_citas = set()

    # This is used to add agency abbreviations to the FR doc info. The field is useful to the LLM and can't be selected in the FederalRegister.gov 
    # search API endpoint used in final_rules_for_part, which gets all the other docinfo
    all_agency_info = requests.get("https://www.federalregister.gov/api/v1/agencies")
    all_agency_info.raise_for_status()
    all_agency_info = all_agency_info.json()

    for (titleno, part) in cfr_parts:
        partno = part["identifier"] # Can be non-integer
        print(f"Analyzing {titleno} CFR Part {partno}")
        os.makedirs(os.path.join(datadir, "cfr", f"title-{titleno}", f"part-{partno}"), exist_ok=True)
        fr_cita_to_cfr_divs = citations_of_part(titleno, partno, datadir)
        final_rules = final_rules_for_part(titleno, partno, datadir)

        # Map each FR citation to its FR Final Rule document number
        for fr_cita_with_date in fr_cita_to_cfr_divs:
            fr_cita = fr_cita_with_date.split(",", 1)[0]
            
            fr_doc_identified = False
            for rule in final_rules.get("results", []):
                if citation_in_doc(fr_cita, rule):
                    docno = rule["document_number"]
                    if docno not in fr_docs_in_cfr:
                        # Add the short-hands for the issuing agencies
                        agency_names = []
                        agency_abbrvs = []
                        for agency in rule["agency_names"]:
                            try:
                                agency_abbrvs.append(next(agency_info["short_name"] for agency_info in all_agency_info if agency == agency_info["name"]))
                                agency_names.append(agency)
                            except Exception as e:
                                raise ValueError(f"{agency} could not be connected to a an agency short_name: {e}")
                        rule["agencies"] = agency_names
                        rule["agency-shorthand"] = agency_abbrvs
                        
                        fr_docs_in_cfr[docno] = (set(), rule)
                    fr_docs_in_cfr[docno][0].update(fr_cita_to_cfr_divs[fr_cita_with_date])
                    
                    fr_doc_identified = True
                    
            if not fr_doc_identified:
                # TODO: we should have some sense of why an FR citation was skipped
                unaccounted_for_fr_citas.add(fr_cita)
            
    skipped = fetch_final_rules(fr_docs_in_cfr, datadir)

    # Filter out the FR docs we identified but couldn't fetch from FederalRegister.gov and convert the results into a Pandas DataFrame
    skipped_docnos = list(map(lambda s : s[1]["document_number"], skipped))
    fr_docs_to_analyze = {docno: fr_docs_in_cfr[docno] for docno in fr_docs_in_cfr if docno not in skipped_docnos}
    
    fr_docs_in_cfr = {
        "fr-docno": [], 
        "cfr-divs-referenced-in": [], 
        "fr-doc-citation": [], 
        "fr-doc-agencies": [], 
        "fr-doc-agencies-shorthand": [], 
        "fr-doc-title": [], 
        "fr-doc-abstract": [], 
        "fr-doc-publication-date": [], 
        "fr-doc-cfr-parts-affected": []
    }
    
    for docno, (cfr_divs, docinfo) in fr_docs_to_analyze.items():
        fr_docs_in_cfr["fr-docno"].append(docno),
        fr_docs_in_cfr["cfr-divs-referenced-in"].append(cfr_divs),
        fr_docs_in_cfr["fr-doc-citation"].append(docinfo["citation"]),
        fr_docs_in_cfr["fr-doc-agencies"].append(docinfo["agencies"]),
        fr_docs_in_cfr["fr-doc-agencies-shorthand"].append(docinfo["agency-shorthand"]),
        fr_docs_in_cfr["fr-doc-title"].append(docinfo["title"]),
        fr_docs_in_cfr["fr-doc-abstract"].append(docinfo["abstract"]),
        fr_docs_in_cfr["fr-doc-publication-date"].append(docinfo["publication_date"]),
        fr_docs_in_cfr["fr-doc-cfr-parts-affected"].append(docinfo["cfr_references"]),
        
    return pd.DataFrame(fr_docs_in_cfr), (skipped, unaccounted_for_fr_citas)


def extract_part_info(titleno, divty, divid, datadir):
    '''
    Fetch the structure of a CFR Title from the eCFR, cache it, and return a list of the component Parts.
    All CFR Titles are divided into Parts, unlike some other subdivisions (Chapter, Subchapter, etc.).
    '''
    structure_path = os.path.join(datadir, "cfr", "structure", f"title-{titleno}.json")    
    try:
        with open(structure_path, "r") as f:
            structure = json.load(f)
    except FileNotFoundError:
        structure = requests.get(f"https://www.ecfr.gov/api/versioner/v1/structure/{ECFR_DATE}/title-{titleno}.json")
        structure.raise_for_status()
        structure = structure.json()
        with open(structure_path, "w") as f:
            json.dump(structure, f)

    def flatten_structure(item):
        flat_structure = [item]
        for child in item.get("children", []):
            flat_structure.extend(flatten_structure(child))
        return flat_structure
    
    flat_structure = flatten_structure(structure)
    div_structure = list(filter(lambda item : item["type"] == divty and item["identifier"] == divid, flat_structure))
    
    if len(div_structure) == 0:
        raise ValueError(f"Unknown input specified: {titleno} CFR {divty} {divid}")
    assert len(div_structure) == 1 and f"WEIRD: {titleno} CFR {divty} {divid} maps to multiple subdivisions of the CFR."
    
    flat_div_structure = flatten_structure(div_structure[0])
    parts_for_div = filter(lambda item : item["type"] == "part" and not item["reserved"], flat_div_structure)
    parts_with_title = list(map(lambda part : (titleno, part), parts_for_div))
    assert len(parts_with_title) > 0 and f"{titleno} CFR {divty} {divid} exists but contains no Parts that aren't reserved."
    
    return parts_with_title


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser("")
    parser.add_argument("datadir", help="The directory to store the results and analyzed data")
    parser.add_argument("--Title", action="append", help="A CFR Title to analyze. This argument can be listed multiple times for multiple Titles.")
    parser.add_argument("--Part", nargs=2, action="append", metavar=("TITLE", "PART"), help="A CFR Title and Part to analyze (e.g., for 40 CFR Part 62, --Part 40 62). This argument can be listed multiple times for multiple Parts.")
    
    args = parser.parse_args()

    os.makedirs(os.path.join(args.datadir, "cfr", "structure"), exist_ok=True)
    cfr_parts = []
    for titleno in args.Title:
        cfr_parts.extend(extract_part_info(titleno, "title", titleno, args.datadir))
    for titleno, partno in args.Part:
        cfr_parts.extend(extract_part_info(titleno, "part", partno, args.datadir))
    
    # TODO: handle status
    fr_doc_data, _ = cfr_to_fr_docs(cfr_parts, args.datadir)
    fr_doc_analysis = llm_analysis(fr_doc_data, args.datadir)

    fr_doc_data = pd.DataFrame(fr_doc_data)
    with open(os.path.join(args.datadir, "fr-doc-data.csv"), "w") as outf:
        fr_doc_data.to_csv(outf)
