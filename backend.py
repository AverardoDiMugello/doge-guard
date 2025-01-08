import cohere
import datetime
from dotenv import load_dotenv
import hnswlib
import json
import lxml.etree as ET
import os
import pandas as pd
from pathlib import Path
import re
import requests
import sys
import time
import toml
from unstructured.partition.html import partition_html
from unstructured.chunking.title import chunk_by_title
import uuid

########################################
# Global constants for parsing the CFR #
########################################

# Since a freeze in issued regulations is likely shortly after the inauguration, a good way to have synchronized data and results
# across multiple users is to have a fixed end date for data, likely whenever that rule freeze is put in place.
ECFR_DATE = "2024-12-30"
CFR_TITLES = [str(num) for num in range(1, 51)]
# For now, we aren't using the date. Maybe when diff-ing algo
# fr_citation_pattern = r"([0-9]+ FR [0-9]+, (Jan.|Feb.|Mar.|Apr.|May|June|July|Aug.|Sept.|Oct.|Nov.|Dec.) [0-9]{1,2}, [0-9]{4})"
citation_regex = re.compile(r"[0-9]+ FR [0-9]+")
non_alphabet_regex = re.compile(r"\D")

#####################################
# Global constants for using Cohere #
#####################################

load_dotenv()
api_key = os.getenv("COHERE_API_KEY")
co = cohere.Client(api_key)

USING_COHERE_TRIAL_KEY = False

# THESE ARE MUTATED!!!
TOKENS = 0
CALLS = 0
RATE_LIMIT_PAUSES = 0

##############################################
# Functions and classes for LLM RAG analysis #
##############################################

def rate_limit_check(additional_toks):
    '''
    Enforces pauses for Cohere's rate limits. Not thread-safe. Call before every Cohere request. E.g.,
    
    texts = [item["text"] for item in batch]   
    rate_limit_check(sum(map(lambda x : len(x), texts)))
    docs_embs_batch = co.embed(
        texts=texts, model="embed-english-v3.0", input_type="search_document"
    ).embeddings        
    '''
    global TOKENS
    global CALLS
    global RATE_LIMIT_PAUSES

    if USING_COHERE_TRIAL_KEY:
        # Trial key rate limits
        API_CALL_RATE_LIMIT = 10 # calls/min
        TOKEN_RATE_LIMIT = 100000 # tokens/min
    else:
        # Production key rate limits
        API_CALL_RATE_LIMIT = 100000 # calls/min guess? This is supposedly 2,000 calls/min for embed, but experimentally, this limit worked...
        TOKEN_RATE_LIMIT = 2000000 # tokens/min

    print("--- Rate Limit Pause internals ---")
    print("TOKENS:", TOKENS)
    print("CALLS:", CALLS)
    print("RATE_LIMIT_PAUSES:", RATE_LIMIT_PAUSES)
    print("-----------------------------------")

    CALLS += 1
    TOKENS += additional_toks
    if TOKENS / TOKEN_RATE_LIMIT - RATE_LIMIT_PAUSES >= 1 or CALLS / API_CALL_RATE_LIMIT >= 1:
        print("\tPause for rate-limit...")
        time.sleep(60)
        CALLS = 0
        RATE_LIMIT_PAUSES += 1


class VectorStoreIndex:
    '''
    Interface for creating and calling an Hnswlib vectorstore for a single document
    '''
    def __init__(self, raw_doc_path, index_path, outf=sys.stdout):
        self.raw_doc_path = raw_doc_path
        self.docs = []
        self.docs_embs = []
        self.retrieve_top_k = 15
        self.rerank_top_k = 5
        self.idx = hnswlib.Index(space="ip", dim=1024)
        self.input_doc_tok_len = 0
        self.input_doc_word_len = 0
        self.outf = outf
        
        self.load_and_chunk()
        if os.path.exists(index_path):
            self.idx.load_index(index_path)
        else:
            self.embed()
            self.index(index_path)
        print(f"Indexing complete with {self.idx.get_current_count()} document chunks.", file=self.outf)


    def load_and_chunk(self):
        print("Loading documents...", file=self.outf)

        with open(self.raw_doc_path, "r", encoding="windows-1252") as f:
            html_content = f.read()
        
        t0 = time.time()
        print("\tPartition HTML", file=self.outf)
        elements = partition_html(text=html_content)
        print(f"\t\t{time.time() - t0} s", file=self.outf)
        
        t0 = time.time()
        print("\tChunk by title", file=self.outf)
        chunks = chunk_by_title(elements)
        print(f"\t\t{time.time() - t0} s", file=self.outf)
        
        print(f"\tChunking {self.raw_doc_path}", end="", file=self.outf)
        t0 = time.time()
        for chunk in chunks:
            chunk = str(chunk)
            self.input_doc_tok_len += len(chunk)
            self.input_doc_word_len += len(chunk.split(" "))
            self.docs.append(
                {
                    "title": self.raw_doc_path,
                    "text": chunk,
                }
            )
        print(f"\t\t{time.time() - t0} s", file=self.outf)

    
    def embed(self):
        print("Embedding document chunks...", file=self.outf)

        batch_size = 90
        self.docs_len = len(self.docs)
        for i in range(0, self.docs_len, batch_size):
            batch = self.docs[i : min(i + batch_size, self.docs_len)]
            texts = [item["text"] for item in batch]
            
            rate_limit_check(sum(map(lambda x : len(x), texts)))
            print(f"\tSending...", file=self.outf)
            docs_embs_batch = co.embed(
                texts=texts, model="embed-english-v3.0", input_type="search_document"
            ).embeddings
            self.docs_embs.extend(docs_embs_batch)
            
   
    def index(self, index_path):
        print("Indexing document chunks...", file=self.outf)

        self.idx.init_index(max_elements=self.docs_len, ef_construction=512, M=64)
        self.idx.add_items(self.docs_embs, list(range(len(self.docs_embs))))

        print("Saving idx to disc...", file=self.outf)
        self.idx.save_index(index_path)

    
    def retrieve(self, query: str):
        # Retrieve
        rate_limit_check(len(query))
        query_emb = co.embed(
            texts=[query], model="embed-english-v3.0", input_type="search_query"
        ).embeddings

        doc_ids = self.idx.knn_query(query_emb, k=self.retrieve_top_k)[0][0]

        # Rerank
        rank_fields = ["title", "text"]

        docs_to_rerank = [self.docs[doc_id] for doc_id in doc_ids]
        print("Docs to rerank:", docs_to_rerank, file=self.outf)

        rate_limit_check(len(query))
        rerank_results = co.rerank(
            query=query,
            documents=docs_to_rerank,
            top_n=self.rerank_top_k,
            model="rerank-english-v3.0",
            rank_fields=rank_fields
        )

        doc_ids_reranked = [doc_ids[result.index] for result in rerank_results.results]

        docs_retrieved = []
        for doc_id in doc_ids_reranked:
            docs_retrieved.append(
                {
                    "title": self.docs[doc_id]["title"],
                    "text": self.docs[doc_id]["text"],
                }
            )

        print("Docs reranked:", docs_retrieved, file=self.outf)

        return docs_retrieved


class Chatbot:
    def __init__(self, vectorstore: VectorStoreIndex, outf=sys.stdout):
        self.vectorstore = vectorstore
        self.conversation_id = str(uuid.uuid4())
        self.outf = outf
 
    
    def run(self, preamble, prompt):
        result = {}
        print(f"\n{'-'*100}\n", file=self.outf)
        
        try:
            toks_in_query = len(preamble) + len(prompt)

            # Generate search queries (if any)
            rate_limit_check(toks_in_query)
            response = co.chat(
                preamble=preamble,
                message=prompt,
                model="command-r",
                search_queries_only=True
            )

            # If there are search queries, retrieve document chunks and respond
            if response.search_queries:
                print("Retrieving information...", end="", file=self.outf)

                # Retrieve document chunks for each query
                documents = []
                for query in response.search_queries:
                    documents.extend(self.vectorstore.retrieve(query.text))
                result["chunks_used"] = documents
                result["fr_doc_tok_len"] = self.vectorstore.input_doc_tok_len
                result["fr_doc_word_len"] = self.vectorstore.input_doc_word_len

                # Use document chunks to respond
                rate_limit_check(toks_in_query)
                response = co.chat(
                    preamble=preamble,
                    message=prompt,
                    model="command-r-plus",
                    documents=documents,
                    conversation_id=self.conversation_id,
                )
            else:
                raise Exception("No search queries identified in prompt")

            # Print the chatbot response, citations, and document
            print("\nChatbot:", response.text, file=self.outf)
            result["answer"] = response.text
            result["citations"] = response.citations

            # Display citations and source documents
            if response.citations:
                print("\n\nCITATIONS:", file=self.outf)
                for citation in response.citations:
                    print(citation, file=self.outf)

                print("\nDOCUMENTS:", file=self.outf)
                for document in response.documents:
                    print(document, file=self.outf)
            result["err_msg"] = ""
        except Exception as e:
            result = {
                "answer": "ERROR",
                "err_msg": f"{e}",
                "citations": [],
                "chunks_used": [],
                "fr_doc_tok_len": self.vectorstore.input_doc_tok_len,
                "fr_doc_word_len": self.vectorstore.input_doc_word_len,
            }

        return result


def llm_analysis(fr_doc_dataset, datadir):
    results = {
        "llm-answer": [], 
        "llm-citations": [], 
        "llm-chunks-used": [],
        "llm-preamble": [],
        "llm-prompt": [],
        "llm-error": [],
        "fr-doc-tok-len": [],
        "fr-doc-word-len": []
    }

    preamble = '''

    ## Task & Context
    You have been given a Final Rule document which is a document published by a U.S. federal government agency that establishes a new regulation. In a Final Rule document, the agency issuing the Rule responds to any significant, relevant issues raised in public comments about the Rule during the rule-making process. For each public comment in the Final Rule, the agency will first describe the comment from the public and then offer the agency's response. You are being asked to look over all of the comments described in this Final Rule and determine if any of the public commenters raised concerns that the agency is not acting with authority from Congress by issuing this rule. You will only answer yes or no.
    '''
    print(fr_doc_dataset.head())
    for _, fr_doc_data in fr_doc_dataset.iterrows():
        print(fr_doc_data)
        rule_dir = os.path.join(datadir, "final_rules", fr_doc_data["fr-docno"])
        rule_html = os.path.join(rule_dir, "rule.html")
        index_path = os.path.join(rule_dir, "index")
        # TODO: change results.txt to a .json
        results_txt = open(os.path.join(rule_dir, "results.txt"), "w")

        agencies = " or ".join([f"the {a} ({abbrv})" for a, abbrv in zip(fr_doc_data["fr-doc-agencies"], fr_doc_data["fr-doc-agencies-shorthand"])])
        pronoun = "their" if len(fr_doc_data["fr-doc-agencies"]) > 1 else "its"
        
        prompt = f'''
        Did {agencies} receive any public comments questioning {pronoun} legal or statutory authority to issue this Final Rule?
        '''
        vectorstore = VectorStoreIndex(rule_html, index_path, outf=results_txt)
        chatbot = Chatbot(vectorstore, outf=results_txt)
        llm_results = chatbot.run(preamble, prompt)

        results["llm-answer"].append(llm_results["answer"])
        results["llm-citations"].append(llm_results["citations"])
        results["llm-chunks-used"].append(llm_results["chunks_used"])
        results["llm-preamble"].append(preamble)
        results["llm-prompt"].append(prompt)
        results["llm-error"].append(llm_results["err_msg"])
        results["fr-doc-tok-len"].append(llm_results["fr_doc_tok_len"])
        results["fr-doc-word-len"].append(llm_results["fr_doc_word_len"])
        
    return pd.concat([fr_doc_dataset, pd.DataFrame(results)], axis=1)
    

#################################
# Functions for parsing the CFR #
#################################

def citation_in_doc(cita_in_cfr, rule):
    fr_cita, fr_start, fr_stop = rule["citation"], rule["start_page"], rule["end_page"]
    if fr_cita is None:
        # This is rare but can happen, e.g. FR doc 94-27103
        return False
    
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
    print("\t[*] Collecting FR citations... ", end="")
    part_path = os.path.join(datadir, f"cfr-{ECFR_DATE}", f"title-{titleno}", f"part-{partno}", "part.xml")
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
        parent = cita_elem.getparent()
        if parent.tag.startswith("DIV"):
            divname, divty = parent.attrib["N"], parent.attrib["TYPE"]
        elif parent.tag.startswith("EXTRACT"):
            grandparent = parent.getparent()
            if grandparent.tag.startswith("DIV"):
                divname, divty = grandparent.attrib["N"], grandparent.attrib["TYPE"]
            else:
                divname, divty = next(f"{titleno} CFR {partno} {child.text}" for child in parent if child.tag == "HD1"), "EXTRACT"
        fr_citations = set(re.findall(citation_regex, cita_elem.text))
        
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
    print(f"{len(fr_cita_to_cfr_divs)} citations.")
    return fr_cita_to_cfr_divs


def fr_docs_for_part(titleno, partno, datadir):
    '''
    Search FederalRegister.gov for all Final Rule documents since 1994 that were marked as affecting the given CFR Part.
    Cache the search results. FR.gov's search API returns a JSON object, returned from this function as a dictionary.
    '''
    print("\t[*] Searching for affecting FR documents... ", end="")
    rule_search_path = os.path.join(datadir, f"cfr-{ECFR_DATE}", f"title-{titleno}", f"part-{partno}", "rules.json")
    try:
        with open(rule_search_path, "r") as f:
            rule_search = json.load(f)
    except FileNotFoundError:
        rule_query = "https://www.federalregister.gov/api/v1/documents.json"
        rule_query += "?per_page=1000&order=newest"
        rule_query += f"&conditions[cfr][title]={titleno}"
        # Some Parts have letters in them (e.g. 15 CFR 4a) and the FederalRegister.gov API lists documents affecting these parts under just
        # the numerical Part, i.e. 15 CFR 4 for the aforementioned example.
        rule_query += f"&conditions[cfr][part]={re.sub(non_alphabet_regex, '', partno)}"
        rule_query += "&conditions[publication_date][gte]=1994-01-01"
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
        
        next_page_url = rule_search.get("next_page_url")
        while next_page_url is not None:
            next_page = requests.get(next_page_url)
            next_page.raise_for_status()
            next_page = next_page.json()
            print(len(next_page["results"]))
            rule_search["results"].extend(next_page["results"])
            next_page_url = next_page.get("next_page_url")    
            
        with open(rule_search_path, "w") as f:
            json.dump(rule_search, f)
    
    result_count = rule_search["count"]
    results = rule_search.get("results", [])
    try:
        # Results are returned 1000 results per page for maximum 10 pages. TODO: fetch the remaining for those above 10,000
        assert result_count == len(results) or result_count > 10000
    except AssertionError as e:
        print(f"result_count = {result_count}, len(results) = {len(results)} ")
        raise e
    print(f"{result_count} documents.")
    
    return results


def fetch_fr_docs(final_rule_docs, datadir):
    '''
    Create the following portion of the database if not created already:
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
        print(f"[*] Fetching FR documents... {i+1}/{num_rules}: {docno}", end="\r", flush=True)
        fr_doc = final_rule_docs[docno][1]

        # Skip existing Final Rule docs
        document_dir = os.path.join(datadir, "final_rules", docno)
        if os.path.exists(document_dir):
            assert os.path.isdir(document_dir) and f"{document_dir} exists but isn't a directory."
            continue

        try:
            # Get the PDF of the rule
            pdf_res = requests.get(fr_doc["pdf_url"])
            pdf_res.raise_for_status()
            assert pdf_res.headers["Content-Type"].startswith("application/pdf")
            
            # Get the HTML and CFR Part of the rule
            html_res = requests.get(fr_doc["body_html_url"])
            html_res.raise_for_status()
            assert html_res.headers["Content-Type"].startswith("text/html")

            details = {}
            details["title"] = fr_doc["title"]
            details["agencies"] = fr_doc["agencies"]
            details["agency_shorthand"] = fr_doc["agency_shorthand"]
            details["abstract"] = fr_doc["abstract"]
            details["body_html_url"] = fr_doc["body_html_url"]
            details["citation"] = fr_doc["citation"]
            details["cfr_references"] = fr_doc["cfr_references"]
            details["document_number"] = docno
            details["end_page"] = fr_doc["end_page"]
            details["pdf_url"] = fr_doc["pdf_url"]
            date = fr_doc["publication_date"].split("-")
            details["publication-date"] = datetime.date(int(date[0]), int(date[1]), int(date[2]))
            details["significant"] = fr_doc["significant"]
            details["start_page"] = fr_doc["start_page"]
        except Exception as e:
            skipped.append((i, fr_doc, e))
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
    
    print(f"[*] Fetching FR documents... {num_rules - len(skipped)}/{num_rules}, {len(skipped)} skipped.", flush=True)
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
    Return the FR doc data and how well the CFR inputs were "covered," i.e. how many FR citations we were able to attribute to documents
    '''
    # This is used to add agency abbreviations to the FR doc info. The field is useful to the LLM but can't be selected in the FederalRegister.gov 
    # search API endpoint used in fr_docs_for_part, which gets all the other docinfo.
    all_agency_info = requests.get("https://www.federalregister.gov/api/v1/agencies")
    all_agency_info.raise_for_status()
    all_agency_info = all_agency_info.json()

    fr_docs_to_analyze = {}
    cfr_part_cov = {}
    
    for (titleno, part) in cfr_parts:
        partno = part["identifier"] # Can be non-integer
        print(f"[*] {titleno} CFR Part {partno}")
        os.makedirs(os.path.join(datadir, f"cfr-{ECFR_DATE}", f"title-{titleno}", f"part-{partno}"), exist_ok=True)
        # Search the eCFR for all the citations of the Federal Register in the given CFR Part
        fr_citas_to_cfr_divs = citations_of_part(titleno, partno, datadir)
        # Search FederalRegister.gov for all documents marked as affecting the given CFR Part
        fr_docs_affecting = fr_docs_for_part(titleno, partno, datadir)
        
        # Attempt to match each FR citation to its FR Final Rule document number
        print("\t[*] Attributing FR citations to a FR document... ", end="")
        fr_docs_attrib_for_part = set()
        fr_citas_unattrib_for_part = set()
        for fr_cita, cfr_divs in fr_citas_to_cfr_divs.items():
            fr_doc_identified = False
            for fr_doc in fr_docs_affecting:
                if citation_in_doc(fr_cita, fr_doc):
                    docno = fr_doc["document_number"]
                    if docno not in fr_docs_to_analyze:
                        # Add the short-hands for the issuing agencies
                        agency_names = []
                        agency_abbrvs = []
                        for agency in fr_doc["agency_names"]:
                            try:
                                agency_abbrvs.append(next(agency_info["short_name"] for agency_info in all_agency_info if agency == agency_info["name"]))
                                agency_names.append(agency)
                            except Exception as e:
                                continue
                        fr_doc["agencies"] = agency_names
                        fr_doc["agency_shorthand"] = agency_abbrvs
                        # Add it to the set of FR docs to analyze {docno: (cfr-divs-affected, docinfo)}
                        fr_docs_to_analyze[docno] = (set(), fr_doc)
                    fr_docs_to_analyze[docno][0].update(cfr_divs)
                    
                    fr_docs_attrib_for_part.add(docno)
                    fr_doc_identified = True

            if not fr_doc_identified:
                fr_citas_unattrib_for_part.add(fr_cita)
    
        num_citas = len(fr_citas_to_cfr_divs)
        num_unattributed = len(fr_citas_unattrib_for_part)
        attrib_count = num_citas - num_unattributed
        print(f"{attrib_count}/{num_citas} citations attributed from {len(fr_docs_affecting)} available documents.")

        cfr_part_cov[(titleno, partno)] = {
            "fr-citations": list(fr_citas_to_cfr_divs.keys()),
            "fr-docs-affecting": list(map(lambda fr_doc : fr_doc["document_number"], fr_docs_affecting)),
            "fr-docs-attributed": list(fr_docs_attrib_for_part),
            "fr-cita-unattributed": list(fr_citas_unattrib_for_part),
        }
    
    # Fetch the FR docs to analyze
    fr_docs_unfetched = fetch_fr_docs(fr_docs_to_analyze, datadir)
    fr_docs_unfetched = list(map(lambda s : s[1]["document_number"], fr_docs_unfetched))

    # Aggregate the FR doc results into a DataFrame
    fr_doc_results = {
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
    
    fr_docs_to_analyze = {docno: docval for docno, docval in fr_docs_to_analyze.items() if docno not in fr_docs_unfetched}
    for docno, (cfr_divs, docinfo) in fr_docs_to_analyze.items():
        fr_doc_results["fr-docno"].append(docno),
        fr_doc_results["cfr-divs-referenced-in"].append(cfr_divs),
        fr_doc_results["fr-doc-citation"].append(docinfo["citation"]),
        fr_doc_results["fr-doc-agencies"].append(docinfo["agencies"]),
        fr_doc_results["fr-doc-agencies-shorthand"].append(docinfo["agency_shorthand"]),
        fr_doc_results["fr-doc-title"].append(docinfo["title"]),
        fr_doc_results["fr-doc-abstract"].append(docinfo["abstract"]),
        fr_doc_results["fr-doc-publication-date"].append(docinfo["publication_date"]),
        fr_doc_results["fr-doc-cfr-parts-affected"].append(docinfo["cfr_references"]),
    fr_doc_results = pd.DataFrame(fr_doc_results)

    # Collect the description of what analysis was done per input CFR Part into a DataFrame
    cfr_part_results = {
        "cfr-title": [],
        "cfr-part": [],
        "fr-citations": [],
        "fr-docs-affecting": [],
        "fr-docs-attributed": [], # FR docnos
        "fr-cita-unattributed": [], # FR citas
        "fr-docs-unfetched": [], # FR docnos
    }

    for (titleno, partno), status in cfr_part_cov.items():
        cfr_part_results["cfr-title"].append(titleno)
        cfr_part_results["cfr-part"].append(partno)
        cfr_part_results["fr-citations"].append(status["fr-citations"])
        cfr_part_results["fr-docs-affecting"].append(status["fr-docs-affecting"])
        cfr_part_results["fr-docs-attributed"].append(status["fr-docs-attributed"])
        cfr_part_results["fr-cita-unattributed"].append(status["fr-cita-unattributed"])
        cfr_part_results["fr-docs-unfetched"].append([docno for docno in status["fr-docs-attributed"] if docno in fr_docs_unfetched])
    cfr_part_results = pd.DataFrame(cfr_part_results)

    return fr_doc_results, cfr_part_results


def extract_part_info(titleno, divty, divid, datadir):
    '''
    Fetch the structure of a CFR Title from the eCFR, cache it, and return a list of the component Parts.
    All CFR Titles are divided into Parts, unlike some other subdivisions (Chapter, Subchapter, etc.).
    '''
    if titleno not in CFR_TITLES:
        raise ValueError(f"Invalid CFR Title {titleno}")
    if titleno == "35":
        raise ValueError(f"Title 35 is fully reserved.")
    
    structure_path = os.path.join(datadir, f"cfr-{ECFR_DATE}", "structure", f"title-{titleno}.json")    
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
        raise ValueError(f"Unknown input: {titleno} CFR {divty} {divid}")
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
    parser.add_argument("--ALL", action="store_true", default=False, help="Analyze all Parts of all CFR Titles. This overrides all other options.")
    parser.add_argument("--Title", action="append", default=[], help="A CFR Title to analyze. This argument can be listed multiple times for multiple Titles.")
    parser.add_argument("--Part", nargs=2, metavar=("TITLE", "PART"), action="append", default=[], help="A CFR Title and Part to analyze (e.g., for 40 CFR Part 62, --Part 40 62). This argument can be listed multiple times for multiple Parts.")
    
    args = parser.parse_args()

    os.makedirs(os.path.join(args.datadir, f"cfr-{ECFR_DATE}", "structure"), exist_ok=True)
    cfr_parts = []
    if args.ALL:
        for titleno in CFR_TITLES:
            if titleno != "35":
                cfr_parts.extend(extract_part_info(titleno, "title", titleno, args.datadir))
    else:
        for titleno in args.Title:
            cfr_parts.extend(extract_part_info(titleno, "title", titleno, args.datadir))
        for titleno, partno in args.Part:
            cfr_parts.extend(extract_part_info(titleno, "part", partno, args.datadir))

    fr_doc_data, cfr_cov = cfr_to_fr_docs(cfr_parts, args.datadir)
    fr_doc_analysis = llm_analysis(fr_doc_data, args.datadir)
    
    os.makedirs(os.path.join(args.datadir, "results"), exist_ok=True)
    with open(os.path.join(args.datadir, "results", "fr_doc_analysis.csv"), "w") as outf:
        fr_doc_analysis.to_csv(outf)
    with open(os.path.join(args.datadir, "results", "cfr_coverage.csv"), "w") as outf:
        cfr_cov.to_csv(outf)
    