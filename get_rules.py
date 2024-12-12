import datetime
import os
import pandas
import requests
import toml
from pathlib import Path

def get_rules(in_f, out_dir):
    all_agency_info = requests.get("https://www.federalregister.gov/api/v1/agencies")
    all_agency_info.raise_for_status()
    all_agency_info = all_agency_info.json()

    skipped = []
    search_results = pandas.read_csv(in_f, sep=",")
    num_rules = len(search_results.index)
    for i, row in search_results.iterrows():
        doc_num = row['document_number'].strip()
        print(f"{i+1}/{num_rules}: {doc_num}")
        
        try:
            # Get the PDF of the rule
            pdf_res = requests.get(row['pdf_url'])
            pdf_res.raise_for_status()
            assert pdf_res.headers["Content-Type"].startswith("application/pdf")
            
            # Get the HTML of the rule
            html_res = requests.get(f"https://www.federalregister.gov/api/v1/documents/{doc_num}.json?fields[]=body_html_url")
            html_res.raise_for_status()
            assert html_res.headers["Content-Type"].startswith("application/json")
            html_res = requests.get(html_res.json()["body_html_url"])
            html_res.raise_for_status()
            assert html_res.headers["Content-Type"].startswith("text/html")

            # Get the short-hand for each agency
            agency_names = []
            agency_abbrvs = []
            for agency in row["agency_names"].split("; "):
                try:
                    agency_abbrvs.append(next(agency_info["short_name"] for agency_info in all_agency_info if agency == agency_info["name"]))
                    agency_names.append(agency)
                except Exception as e:
                    continue

            details = {}
            details['title'] = row['title']
            details['agencies'] = agency_names
            details['agency-shorthand'] = agency_abbrvs
            details['abstract'] = row['abstract']
            details['citation'] = row['citation']
            date = row['publication_date'].split("/")
            details['publication-date'] = datetime.date(int(date[2]), int(date[0]), int(date[1]))
        except Exception as e:
            skipped.append((in_f, i, row, e))
            continue
        
        document_dir = Path(os.path.join(out_dir, doc_num))
        document_dir.mkdir(parents=True, exist_ok=True)

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
    

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs='+', help="Input .csv file from www.federalregister.gov/documents/search")
    parser.add_argument("--output", "-o", help="Output directory for the rules")

    args = parser.parse_args()
    skipped = []
    for inp in args.inputs:
        print("Getting rules for", inp)
        skipped = get_rules(inp, args.output)
        skipped.extend(skipped)
    print("Num skipped:", len(skipped))
    print("Skipped:", skipped)

