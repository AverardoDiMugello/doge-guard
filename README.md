# Doge Guard

Doge Guard is a tool for finding regulation that is unconstitutional in light of [West Virginia v. EPA](https://en.wikipedia.org/wiki/West_Virginia_v._EPA). This decision ruled that federal executive agencies must have clear authorization from Congress to make rules that have major national impacts or policy significance. More information on this ruling can be found in this [Congressional Research Service report](https://crsreports.congress.gov/product/pdf/IF/IF12077).

Federal regulations are published in the [Federal Register](https://www.federalregister.gov/) in documents called Final Rules. The rulemaking process for federal agencies is governed by the Administrative Procedure Act. As part of this process, regulators are required to accept and respond to comments from the public during the development of the rule. In a regulation's Final Rule document, the issuing agency must respond to all relevant comments from the public. More information on the rulemaking process can be found at [regulations.gov](https://www.regulations.gov/learn).

Doge Guard is a simple [RAG](https://en.wikipedia.org/wiki/Retrieval-augmented_generation) application that uses an LLM to analyze a Final Rule document, detect if any commenter disputed the agency's statutory authority to make the rule, then output yes or no, and if the answer is yes, include citations to the specific comments.

The name "Doge Guard" was a suggestion from Grok.

## Results

Doge Guard results include the LLM's Yes/No decision, all documents it used to make this decision, the prompt and preamble used, and a large amount of information about the document, including its document number, issuing agencies, abstract, and affected CFR parts.

Some results have been published as Releases here on GitHub. Click the Releases link in the options to the right of this document to download them. The results [currently released](https://github.com/AverardoDiMugello/doge-guard/releases/tag/v0.1-pre-release) cover every Final Rule entered into the Federal Register since the _West Virginia v. EPA_ decision: June 30th, 2022 through December 31st, 2024.

Results may be periodically releaed as Doge Guard changes. Breaking changes to the result data schema will be reflected in version number increments to Doge Guard.

To generate results for yourself, follow the guide below.

## User Guide

### Environment Setup

First, install the python dependencies.

```
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Next, we need to setup access to the LLM. Doge Guard uses Cohere for its LLM, embeddings, and re-rankers. To access these, go to [Cohere's website](https://cohere.com/) and create an account and API key. For testing that your Doge Guard setup works, you can use a trial API key initially, which allows free access at tight rate-limits for 10,000 API calls per month, but in order to run serious workloads you will need a production key. The entire development of Doge Guard cost <$2 with a production key, so I recommend just getting a production one.

Once you have an account and API key, create a file called `.env` in the root directory of the `doge-guard` project (i.e., the same folder as this README.md file) and save the API key to that file like this:

```
COHERE_API_KEY=YourAPIKeyHere
```

### Get Data

First create a folder in this repository called `documents`. This folder will store all of the data used by Doge Guard.

#### Search For Regulations

Make a folder in documents called `search_results`. Federal regulations can be found at the [Federal Register website](https://www.federalregister.gov/documents/search) using their search function. In filters, under Document Category, check Rule, so that you only get Final Rule documents. Enter any other filters for the regulations you want to examine, then click Search, then click "CSV/Excel" to download a spreadsheet of search resuts. Save them in the folder you just created. Don't download individual rules; the next step will do that for us.

The website caps search results at 1000 entries per download, so you may need to break up the results you want using the filters. For example, if you want a year's worth of regulations from all agencies, which is typically about 3,000 final rules, you could download four search results, one for each quarter of the year.

The rest of this guide uses the example of analyzing every Final Rule from every federal agency in Q3 and Q4 of 2022, which is 1,601 documents. To get these regulations from the Federal Register search engine, check Rule in Document Category, check Range in Publication Date and enter 7/01/2022 in On Or After and 9/30/2022 in On Or Before, then click Search, then click CSV/Excel, and save as `documents/search_results/rules_2022_Q3.csv`. Then repeat these steps with 10/01/2022 and 12/31/2022 in the Publication Date Range and save as `documents/search_results/rules_2022_Q4.csv`.

#### Get The Rules

Run get_rules.py with one or more search result files from the Federal Register and an output directory inside documents. This will set up the workspace in the proper format for processing. This step is only querying public USG API's, so it won't cost you anything. For the 1,601 Final Rules published in Q3 and Q4 of 2022, this took ~40 minutes to run.

```
python get_rules.py documents/search_results/rules_2022_Q3.csv documents/search_results/rules_2022_Q4.csv -o documents/rules_2022
```

At the end of this running, you may get output that indicates some rules were skipped due to internal server errors with the Federal Register API. In this event, either build a search results csv file with just those rules that were skipped or construct the workspace by hand. The number of skipped should be few if not zero.

### Get Results

#### Run The RAG

Make a folder in `documents` called `results` to store the application's outputs. Then, you can either specify individual rule workspaces or a directory of rule workspaces. This program _will_ call the Cohere API, and you _will_ be charged if you are using a production API key. If you are using a trial API key specify the --using-cohere-trial-key option in the below commands to adjust the rate limits accordingly. Processing the 1,601 Final Rules for 2022 Q3 and Q4 cost $9.10 and took 2.5 hours.

```
# Run one rule, default output filename (out.csv)
python rag.py documents/rules_2022/2022-12376

# Run two rules, default output filename, with a trial API key (not recommended)
python rag.py documents/rules_2022/2022-12376 documents/rules_2022/2022-28471 --using-cohere-trial-key

# Run a directory of rules, like the one made by get_rules.py, output results to rules_2022_q3_q4_all_results.csv
python rag.py documents/rules_2022 -o documents/results/rules_2022_q3_q4_all_results.csv
```

#### Analyze The Results

```
python visualize.py documents/results/rules_2022_q3_q4_all_results.csv
```

#### Extract Only The "Yes" Results

```
python yes_results.py documents/results/rules_2022_q3_q4_all_results.csv -o documents/results/rules_2022_q3_q4_yes_results.csv
```
