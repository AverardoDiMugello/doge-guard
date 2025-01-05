import os
import time
from sys import stdout

import cohere
import hnswlib
import pandas as pd
import toml
import uuid
from dotenv import load_dotenv
from unstructured.partition.html import partition_html
from unstructured.chunking.title import chunk_by_title

load_dotenv()
api_key = os.getenv("COHERE_API_KEY")
co = cohere.Client(api_key)

USING_COHERE_TRIAL_KEY = False

TOKENS = 0
CALLS = 0
RATE_LIMIT_PAUSES = 0

def rate_limit_check(additional_toks):
    global TOKENS
    global CALLS
    global RATE_LIMIT_PAUSES

    if USING_COHERE_TRIAL_KEY:
        # Trial key rate limits
        API_CALL_RATE_LIMIT = 10 # calls/min
        TOKEN_RATE_LIMIT = 100000 # tokens/min
    else:
        # Production key rate limits
        API_CALL_RATE_LIMIT = 100000 # calls/min # guess??
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
    def __init__(self, raw_doc_path, index_path, outf=stdout):
        self.raw_doc_path = raw_doc_path
        self.docs = []
        self.docs_embs = []
        self.retrieve_top_k = 15
        self.rerank_top_k = 5
        self.idx = hnswlib.Index(space="ip", dim=1024)
        self.total_chunk_len = 0
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
            self.total_chunk_len += len(chunk)
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
    def __init__(self, vectorstore: VectorStoreIndex, outf=stdout):
        self.vectorstore = vectorstore
        self.conversation_id = str(uuid.uuid4())
        self.outf = outf
 
    
    def run(self, preamble, prompt):
        result = {}
        print(f"\n{'-'*100}\n", file=self.outf)
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
            result["documents"] = documents
            result["rule_length"] = self.vectorstore.total_chunk_len

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

        return result


def evaluate_one(rule_dir):
    rule_html = os.path.join(rule_dir, "rule.html")
    index_path = os.path.join(rule_dir, "index")
    results_txt = open(os.path.join(rule_dir, "results.txt"), "w")

    details = open(os.path.join(rule_dir, "details.toml"), "r").read()
    details = toml.loads(details)
    
    print("Rule:", rule_dir)
    print("Title:", details["title"])
    print("Agencies:", "; ".join(details["agencies"]))
    print("Abstract:", details["abstract"])
    print()

    preamble = '''

    ## Task & Context
    You have been given a Final Rule document which is a document published by a U.S. federal government agency that establishes a new regulation. In a Final Rule document, the agency issuing the Rule responds to any significant, relevant issues raised in public comments about the Rule during the rule-making process. For each public comment in the Final Rule, the agency will first describe the comment from the public and then offer the agency's response. You are being asked to look over all of the comments described in this Final Rule and determine if any of the public commenters raised concerns that the agency is not acting with authority from Congress by issuing this rule. You will only answer yes or no.
    '''

    agencies = " or ".join([f"the {a} ({abbrv})" for a, abbrv in zip(details["agencies"], details["agency-shorthand"])])
    pronoun = "their" if len(details["agencies"]) > 1 else "its"
    prompt = f'''
    Did {agencies} receive any public comments questioning {pronoun} legal or statutory authority to issue this Final Rule?
    '''

    print("Prompt:", prompt)
    print()

    vectorstore = VectorStoreIndex(rule_html, index_path, outf=results_txt)
    chatbot = Chatbot(vectorstore, outf=results_txt)
    
    result = chatbot.run(preamble, prompt)
    
    result["title"] = details["title"]
    result["agencies"] = details["agencies"]
    result["agency-shorthand"] = details["agency-shorthand"]
    result["abstract"] = details["abstract"]
    result["citation"] = details["citation"]
    result["publication-date"] = details["publication-date"]
    result["cfr-references"] = details["cfr-references"]
    result["preamble"] = preamble
    result["prompt"] = prompt
    result["rule_dir"] = rule_dir
    
    return result


def evaluate_batch(rules_dir):
    results = {"answer": [], "citations": [], "documents": [], "title": [], "agencies": [], "agency-shorthand": [], "abstract": [], "citation": [], "publication-date": [], "cfr-references": [], "preamble": [], "prompt": [], "rule_length": [], "rule_dir": []}

    skipped = []
    num_to_eval = sum([1 for _ in os.scandir(rules_dir)])
    for i, rule_dir in enumerate(os.scandir(rules_dir)):
        print(f"{i+1}/{num_to_eval}")
        try:
            if is_valid_workspace(rule_dir):
                result = evaluate_one(rule_dir)
                results["answer"].append(result["answer"])
                results["citations"].append(result["citations"])
                results["documents"].append(result["documents"])
                results["title"].append(result["title"])
                results["agencies"].append(result["agencies"])
                results["agency-shorthand"].append(result["agency-shorthand"])
                results["abstract"].append(result["abstract"])
                results["citation"].append(result["citation"])
                results["publication-date"].append(result["publication-date"])
                results["cfr-references"].append(result["cfr-references"])
                results["preamble"].append(result["preamble"])
                results["prompt"].append(result["prompt"])
                results["rule_length"].append(result["rule_length"])
                # evaluate_one get a direntry when we call it vs. a string when main calls it, so we ignore what it set for rule_dir
                results["rule_dir"].append(rule_dir.name)
            else:
                raise ValueError(f"{rule_dir} does not contain a valid workspace! Needs a details.toml and a rule.html")
        except Exception as e:
            skipped.append((rule_dir, f"{e}"))

    print("Skipped:", skipped)
    return results


# A valid workspace just needs a details.toml and a rule.html
def is_valid_workspace(rule_dir):
    has_details = False
    has_rule = False
    for f in os.scandir(rule_dir):
        if f.name == "details.toml":
            has_details = True
        elif f.name == "rule.html":
            has_rule = True
    
    return has_details and has_rule


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs='+', help="One or more space-separated paths, each to a rule workspace or a directory of rule workspaces.")
    parser.add_argument("--output", "-o", help="An optional output .csv file to store batch results.")
    parser.add_argument("--using-cohere-trial-key", action="store_true", help="Set this argument if you are using a Cohere trial API key. This will cause rate limits to be adjusted accordingly.")
    
    args = parser.parse_args()

    if args.output is not None:
        outf = open(args.output, "w")
    else:
        outf = open("out.csv", "w")

    if args.using_cohere_trial_key:
        USING_COHERE_TRIAL_KEY = True

    final_results = {"rule_dir": [], "answer": [], "citations": [], "documents": [], "title": [], "agencies": [], "agency-shorthand": [], "abstract": [], "citation": [], "publication-date": [], "cfr-references": [], "preamble": [], "prompt": [], "rule_length": []}

    for input in args.inputs:
        if is_valid_workspace(input):
            one_result = evaluate_one(input)
            
            final_results["answer"].append(one_result["answer"])
            final_results["citations"].append(one_result["citations"])
            final_results["documents"].append(one_result["documents"])
            final_results["title"].append(one_result["title"])
            final_results["agencies"].append(one_result["agencies"])
            final_results["agency-shorthand"].append(one_result["agency-shorthand"])
            final_results["abstract"].append(one_result["abstract"])
            final_results["citation"].append(one_result["citation"])
            final_results["publication-date"].append(one_result["publication-date"])
            final_results["cfr-references"].append(one_result["cfr-references"])
            final_results["preamble"].append(one_result["preamble"])
            final_results["prompt"].append(one_result["prompt"])
            final_results["rule_length"].append(one_result["rule_length"])
            final_results["rule_dir"].append(one_result["rule_dir"])
        else:
            batch_results = evaluate_batch(input)
            
            final_results["answer"].extend(batch_results["answer"])
            final_results["citations"].extend(batch_results["citations"])
            final_results["documents"].extend(batch_results["documents"])
            final_results["title"].extend(batch_results["title"])
            final_results["agencies"].extend(batch_results["agencies"])
            final_results["agency-shorthand"].extend(batch_results["agency-shorthand"])
            final_results["abstract"].extend(batch_results["abstract"])
            final_results["citation"].extend(batch_results["citation"])
            final_results["publication-date"].extend(batch_results["publication-date"])
            final_results["cfr-references"].extend(batch_results["cfr-references"])
            final_results["preamble"].extend(batch_results["preamble"])
            final_results["prompt"].extend(batch_results["prompt"])
            final_results["rule_length"].extend(batch_results["rule_length"])
            final_results["rule_dir"].extend(batch_results["rule_dir"])

    final_results = pd.DataFrame(final_results)
    final_results.to_csv(outf)
    print("Results saved to", args.output if args.output is not None else "out.csv")
