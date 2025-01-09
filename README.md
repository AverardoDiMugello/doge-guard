# Doge Guard

Doge Guard uses LLM [RAG](https://en.wikipedia.org/wiki/Retrieval-augmented_generation) to compile a list of CFR sections and Federal Register Final Rules whose statutory authority was contested by the public during rulemaking. The LLM cites its sources from the FR Final Rule. Results for certain CFR Parts are available in CSV/Excel format as [releases on GitHub.](https://github.com/AverardoDiMugello/doge-guard/releases)

## Introduction

Doge Guard is a tool for finding unconstitutional regulation. In 2022, the U.S. Supreme Court ruled in [_West Virginia v. EPA_](https://en.wikipedia.org/wiki/West_Virginia_v._EPA) that federal executive agencies must have clear authorization from Congress to make rules that have major national impacts or policy significance. A major rule lacking clear statutory approval is unconstitutional and not to be enforced. The U.S. Code of Federal Regulations (CFR) is the roughly 180,000 word list of regulations that are active law in the United States. It is too large and complex for a small team to manually triage for regulations that fail the Supreme Court's requirements. This is where Doge Guard comes in.

Federal agencies modify the CFR through a process called [rulemaking](https://www.regulations.gov/learn) established by the Administrative Procedure Act of 1946. Rulemaking is intimately tied to a publication called the Federal Register (FR). First, an agency proposes a new rule by publishing a document in the Federal Register. Then, the proposed rule undergoes a period of public comment and possible iteration. Finally, an agency publishes a Final Rule in the Federal Register which summarizes and addresses the public comments and specifies the changes to the CFR. To use a software analogy, a Final Rule from the Federal Register is a "commit" to the CFR whose "commit message" summarizes public comments on the changes. The Federal Register acts as a database of these "commits" and by extension a database of public comments on every single regulation in U.S. law. Doge Guard analyzes these comments to create a list of regulations whose statutory authority was contested by the public during rulemaking. This list can then be reviewed by policy and legal experts to determine what active rules are unconstitutional. Unlike a software commit, a Final Rule is unstructured. The CFR changes and the summary of and response to public comment are in natural language and inconsistent formats. An LLM is a natural tool to reach for in these circumstances.

Doge Guard performs two tasks. First, it attributes sections of the CFR to the Federal Register documents that produced them. Then, for each of those documents, it prompts an LLM with the question "Did _agency_ receive any public comments questioning its legal or statutory authority to issue this Final Rule?". If the answer is yes, the LLM cites excerpts from the Federal Register document containing the relevant comments. Doge Guard outputs a list of Federal Register documents, the specific sections of the CFR they modified, the answer to the prompt, citations for the answer, and several other relevant data. The output list includes the word counts of the flagged CFR sections, so offending Federal Register documents can be sorted and triaged in order of how much text they added to the CFR. Additional tools for policy or legal experts to triage the results are on the development roadmap.

The name "Doge Guard" was a suggestion from Grok when given a description of this tool.

Some results have been published as Releases here on GitHub. Click [here](https://github.com/AverardoDiMugello/doge-guard/releases) or in the Releases link in the options to the right of this document to download them.

The v0.1 proof-of-concept of this tool did not decompose the CFR into Federal Register documents; it only analyzed documents from a given time slice of the Federal Register. The results of that proof-of-concept are available [here](https://github.com/AverardoDiMugello/doge-guard/releases/tag/v0.1-pre-release), and the infamous X thread discussing those results is available [here.](https://x.com/DiMugello/status/1868022889368400007) These results cover every Final Rule entered into the Federal Register since the _West Virginia v. EPA_ decision: June 30th, 2022 through December 31st, 2024.

Doge Guard is currently close to a v1.0 release. The only item left is to update the analysis script from the v0.1 proof-of-concept schema to the current schema. Breaking changes to the result data schema will be reflected in major version number increments to Doge Guard. Other changes, including performance enhancements, post-processing improvements, an analysis front-end, etc., that do not break the result schema will be reflected in minor version increments.

v1.0 pre-release results for 40 CFR Parts 50 and 180 are available [here](https://github.com/AverardoDiMugello/doge-guard/releases). Since the analysis script for the new schema are still outstanding, you will have to use whatever your favorite CSV/Excel analysis method is yourself to make use of the pre-release results. To generate results for yourself, follow the guide below, but I warn you: meaningful jobs take a long time (for now).

## User Guide

### Setup Environment

First, install the python dependencies.

```
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Next, we need to setup access to the LLM. Doge Guard uses Cohere for its LLM, embeddings, and re-rankers. To access these, go to [Cohere's website](https://cohere.com/) and create an account and API key. For testing that your Doge Guard setup works, you can use a trial API key initially, which allows free access at tight rate-limits for 10,000 API calls per month, but in order to run serious workloads you will need a production key. The entire development of Doge Guard cost <$2 with a production key, so I recommend just getting one.

Once you have an account and API key, create a file called `.env` in the root directory of the `doge-guard` project (i.e., the same folder as this README.md file) and save the API key to that file like this:

```
COHERE_API_KEY=YourAPIKeyHere
```

### Run

The input parameters to `backend.py` currently allow you to specify one or more of the following:

- A Title
- A Title and Part

Additionally, you must specify a directory to hold the retrieved documents. You shouldn't do this yet, but you _can_ specify `--ALL` to analyze the entire CFR. Currently, this will take over 24 hours. Doge Guard's current implementation is a naive, synchronous, serial pipeline that is intuitive to parallelize, so significant performance gains should be possible. In the meantime, Doge Guard makes good use of cacheing, so it will be dramatically quicker each time you run it after the first.

```
# Print the user guide
python backend.py --help

# To analyze 40 CFR Part 50
python backend.py --Part 40 50 documents/

# To analyze 40 CFR Parts 50 and 180
python backend.py --Part 40 50 --Part 40 180 documents/

# To analyze all of Title 40
python backend.py --Title 40 documents/

# To analyze all Titles 1-7
python backend.py --Title 1 --Title 2 --Title 3 --Title 4 --Title 5 --Title 6 --Title 7 documents/

# To analyze all Titles
python backend.py --ALL documents/
```

### Analyze Results

_Coming soon._
