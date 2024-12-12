# DOGE Guard

Doge Guard is a tool for finding regulation that is unconstitutional in light of [West Virginia v. EPA](https://en.wikipedia.org/wiki/West_Virginia_v._EPA). This decision ruled that federal executive agencies must have clear authorization from Congress to make rules that have major national impacts or policy significance. More information on this ruling can be found in this [Congressional Research Service report](https://crsreports.congress.gov/product/pdf/IF/IF12077).

Federal regulations are published in the [Federal Register](https://www.federalregister.gov/) in documents called Final Rules. The rulemaking process for federal agencies is governed by the Administrative Procedure Act. As part of this process, regulators are required to accept and respond to comments from the public during the development of the rule. In a regulation's Final Rule document, the issuing agency must respond to all relevant comments from the public. More information on the rulemaking process can be found at [regulations.gov](https://www.regulations.gov/learn).

Doge Guard is a simple [RAG](https://en.wikipedia.org/wiki/Retrieval-augmented_generation) application that uses an LLM to analyze a Final Rule document, detect if any commenter disputed the agency's statutory authority to make the rule, then output yes or no, and if the answer is yes, include citations to the specific comments.

## Results

TODO: Link to releases for 2023 and 2024

## User Guide

### Environment Setup

First, install the python dependencies.

```
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Next, create a Cohere API key and a .env file.

```
COHERE_API_KEY=YourAPIKeyHere
```

### Get Data

First create a folder in this repository called "documents". This folder will store all of the data used by Doge Guard.

#### Search For Regulations

Make a folder in documents called "search_results". Federal regulations can be found at the [Federal Register website](https://www.federalregister.gov/documents/search) using their search function. In filters, under Document Category, check Rule, so that you only get Final Rule documents. Enter any other filters for the regulations you want to examine, then click search, then click "CSV/Excel" to download a spreadsheet of search resuts. Save them in the folder you just created. Don't download individual rules; the next step will do that for us.

The website caps search results at 1000 entries per download, so you may need to break up the results you want using the filters. For example, if you want a year's worth of regulations from all agencies, which is typically about 3,000 final rules, you could download four search results, one for each quarter of the year.

#### Get The Rules

Run get_rules.py with one or more search result files from the Federal Register and an output directory inside documents. This will set up the workspace in the proper format for processing.

```
python get_rules.py documents/search_results/rules_2022_Q3.csv documents/search_results/rules_2022_Q4.csv -o documents/rules_2022
```

#### Run The RAG

Make a folder to store your results. Then,

```
python rag.py documents/rules_2022 -o results/rules_2022_all_results.csv
```

#### Analyze The Results

```
python visualize.py results/rules_2022_all_results.csv
```
