# TODOs

Can be done with dummy data:

- NEW FRONT-END PAGE: Document-specific page
- NEW FRONT-END LOGIC AND COMPONENT: Select CFR Parts (input!!)
- NEW FRONT-END COMPONENT: CFR coverage of Parts selected

Needs schema clarity

- NEW BACK-END LOGIC: Guarantee a sorting order
- NEW BACK-END DATA: Add the significant field, the FR document url, and the CFR links to the remote data
- NEW FRONT-END LOGIC: Efficient scrolling for large datasets
- NEW FRONT-END/BACK-END INTEROP: Connect the two

Easy

- NEW FRONT-END COLUMN + LINK: Add a CFR sections list with links to the eCFR as a column in the home table

Dream vision:

1. Analysis has the comment answer, con/lib classification, QuantGov complexity, significant label, summary of the results of the FR document
2. A simple server provides GET requests over the analysis
3. The front-end has an auth and provides links to the eCFR and FederalRegister.gov for an analyst to review, a way to link to specific doc focus pages, and apply/sort-by tags
   - The user logs in
   - The user clicks CFR division he wants and those are fetched
   - The results are displayed
   - The user clicks on a doc focus page
   - The results for that doc are displayed
   - Chat with the doc?

Back-end

1. docs.py

- Input: a list of CFR subdivisioins
- Output: a database of CFR parts and the FR documents that affected them plus a status report on the CFR coverage

2. rag.py

- Input: a list of FR document files to analyze
- Output: a log and results for each FR document and persisted embeddings

3. server.py

- Input: a specified user db and data db to serve
- Output: /get endpoints to the data plus whatever auth methods are needed

4. status.py

- Input: subcommands and other args for querying info about the doc db or user db
- Output: answers to those status commands

5. \_\_main\_\_.py

- Input: commands for querying status or running a pipeline
- Output: the results of the status or pipeline

6. QuantGov?

Front-end

1. Login
2. CFR div selection
   - Checkbox for Title, Chapter, Subchapter, Part for each Title
3. FR doc table results

   - Focus link
   - Doc number with a link federalregister.gov
   - FR citation
   - Unstatutory checkbox
   - Significant checkbox
   - CFR words affected
   - One or two largest CFR divisions affected
   - CFR Parts affected
   - Title

4. FR doc focus

- All information about the doc
- Link to the changes introduced by the doc would be excellent

Database

```
# Basically made one-time then read-only afterwards
cfr-{date}/
    structure/
        title-X.json <- used by docs.py to parse CFR divisions into a CFR Part list
                    // For the input spec, the only structure that matters is the CFR-wide Title Node->Part Node paths
    title-X/
        part-Y/
            rules.json <- used by docs.py to find all the rules that affect a given CFR Part
            part.xml <- used by docs.py to iterate over the subdivisions of a CFR Part
fr_docs/
    doc-no-x/
        details.toml <- used by the front-end for displaying information and serving links for the end-user and the LLM for prompt compiling (agency names)
        rule.html <- used by the LLM to do RAG
        index <- generated and used by rag.py
# Modified every time an analysis is run
results/
    rag/
        {name}/
            details.toml
            doc-no-X/
                log.txt
                results.toml
            ...
        ...
    nlp/
        {name}/
            details.toml
            title-X/
                part-Y/
                    log.txt
                    results.toml
    ...
    pipelines/
        {name}/
            details.toml
            log.txt

users/
```

docs.py runs as a server, input directory and output IPCs are specified over command line
rag.py runs as a server, input IPC and output directory specified over command line
nlp.py runs as a server, input IPC and output directory are specified over command line
server.py runs as a server, input data directories are specified over command line
