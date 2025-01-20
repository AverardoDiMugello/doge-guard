/*
 * Tasks:
 * Input: List of CFR (Title, Part) pairs
 * Output: A CSV file containing LLM results per FR document attributed to any CFR division from the input
 * Algo:
 *  Stage 0. Parse inputs
 *
 *  🤨 1. Cli
 *  ✅ 2. Convert Cli args into a list of (Title, Part) tuples
 *
 *  Stage 1. Collect documents
 *
 *  1. For title, part in input, aggregate information for fr_docs_to_analyze and cfr_part_cov:
 *      a. # Search the eCFR for all the citations of the Federal Register in the given CFR Part
 *          fr_citas_to_cfr_divs = citations_of_part(titleno, partno, datadir)
 *          1 http request or file read if cached, self-contained
 *      b. # Search FederalRegister.gov for all documents marked as affecting the given CFR Part
 *          fr_docs_affecting = fr_docs_for_part(titleno, partno, datadir)
 *          >= 1 http request or file read if cached, self-contained
 *      c. # Attempt to match each FR citation to its FR Final Rule document number
 *          O(n^2) loop
 *      d. # Aggregate (join) results into the two overall collections
 * 2. Fetch all docs for fr_docs_to_analyze and return the unfetched
 *      a. Fetch PDF
 *      b. Fetch HTML
 * 3. Create the pandas result DataFrame
 *
 * 0 can run concurrently across different Titles but if it has to be MT then maybe not worth it
 * 1a and 1b can run concurrently
 * 1c depends on 1a and 1b to finish and should probably just be synchronous for now
 * 2 needs 1 to finish
 * 2a and 2b can run concurrently
 * 3 runs synchronously
 *
 * Stage 2. LLM analysis
 *
 * Iterate over the pandas.DataFame rows, chunk docs, then ask question.
 * Each iteration is independent of the other except for the RATE_LIMIT constants.
 *
 */

use std::collections::{HashMap, HashSet, VecDeque};
use std::fmt::Display;
use std::fs::{create_dir_all, File};
use std::io::{BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::str::FromStr;

use clap::{Parser, Subcommand};
use once_cell::sync::Lazy;
use polars::prelude::*;
use regex::Regex;
use reqwest::{self, IntoUrl};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json;
use serde_with::{serde_as, DisplayFromStr};
use tokio::{self, task::JoinSet};
use tokio_utils::RateLimiter;
use tracing;
use tracing_subscriber;

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
struct CfrPart {
    title: String,
    part: String,
}

#[derive(Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
struct CfrDivInfo {
    name: String,
    ty: String,
    word_count: u32,
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
struct FrCita {
    edition: u32,
    page: u32,
}

impl Display for FrCita {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{0}-{1}", self.edition, self.page)
    }
}

impl FromStr for FrCita {
    type Err = std::io::Error;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let mut fr_cita = s.split(" ");
        let edition = fr_cita.next().unwrap().parse().unwrap();
        assert_eq!(fr_cita.next(), Some("FR"));
        let page = fr_cita.next().unwrap().parse().unwrap();
        assert_eq!(fr_cita.next(), None);
        Ok(FrCita { edition, page })
    }
}

#[derive(Serialize, Deserialize)]
struct FrAllAgencyInfo {
    // These are the only fields we care about in that response
    name: String,
    short_name: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
struct CfrPartAffected {
    chapter: Option<u32>,
    citation_url: Option<String>,
    part: Option<u32>,
    title: u32,
}

#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
struct FrDocNo(String);

impl Display for FrDocNo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl FromStr for FrDocNo {
    type Err = std::io::Error;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Ok(FrDocNo(s.to_string()))
    }
}

#[serde_as]
#[derive(Clone, Serialize, Deserialize)]
struct FrDocInfo {
    r#abstract: Option<String>,
    agency_names: Vec<String>,
    // This field is always None after the initial request to fetch search results,
    // but it is set immediately after and serialized in the cached result.
    // This vector of abbreviations is logically parallel to the agency_names field.
    // Because not all agencies have short-hands in the Federal Register, an empty
    // String indicates no short-hand. We don't take use an Option here, because
    // polars forces us to serialize this field into a JSON String, which doesn't like Options.
    agency_abbrvs: Option<Vec<String>>,
    body_html_url: Option<String>,
    cfr_references: Vec<CfrPartAffected>,
    citation: Option<String>,
    #[serde_as(as = "DisplayFromStr")]
    document_number: FrDocNo,
    end_page: u32,
    publication_date: Option<String>,
    significant: Option<bool>,
    start_page: u32,
    title: Option<String>,
}

impl FrDocInfo {
    fn contains(&self, cita: &FrCita) -> bool {
        if let Some(my_cita) = self.citation.as_ref() {
            let mut my_cita_iter = my_cita.split(" ");
            let my_edition = my_cita_iter.next().unwrap().parse::<u32>().unwrap();
            let same_edition = my_edition == cita.edition;
            assert_eq!(my_cita_iter.next(), Some("FR"));
            let my_start_page = my_cita_iter.next().unwrap().parse::<u32>().unwrap();
            assert_eq!(my_start_page, self.start_page);
            let in_page_range = my_start_page <= cita.page && cita.page <= self.end_page;

            same_edition && in_page_range
        } else {
            // This is rare but can happen, e.g. FR Rule docno 94-27103
            false
        }
    }
}

#[derive(Serialize, Deserialize)]
struct FrDocSearch {
    count: u32,
    description: String,
    total_pages: Option<u32>,
    next_page_url: Option<String>,
    results: Option<Vec<FrDocInfo>>,
}

impl FrDocSearch {
    fn extend(&mut self, other: FrDocSearch) {
        if let Some((results, other)) = self.results.as_mut().zip(other.results) {
            results.extend(other);
        }
    }

    fn result_len(&self) -> usize {
        self.results
            .as_ref()
            .and_then(|r| Some(r.len()))
            .unwrap_or(0)
    }

    fn result_iter(&self) -> FrDocSearchIter {
        FrDocSearchIter {
            results_iter: self.results.as_ref().and_then(|r| Some(r.iter())),
        }
    }
}

struct FrDocSearchIter<'a> {
    results_iter: Option<std::slice::Iter<'a, FrDocInfo>>,
}

impl<'a> Iterator for FrDocSearchIter<'a> {
    type Item = &'a FrDocInfo;
    fn next(&mut self) -> Option<Self::Item> {
        if let Some(iter) = self.results_iter.as_mut() {
            iter.next()
        } else {
            None
        }
    }
}

struct CfrCovInfo {
    fr_citas: Vec<FrCita>,
    fr_docs_affecting: Vec<FrDocNo>,
    fr_docs_attributed: HashSet<FrDocNo>,
    fr_citas_unattributed: HashSet<FrCita>,
}

/// Attempts to load a JSON value from disc using the specified path. If the path doesn't resolve, this will attempt to fetch it
/// from the given url and save it to disc at the specified path. The name parameter is used for logging only.
/// The result is serialized/deserialized from/to an instance of the type parameter T.
async fn load_or_fetch_json<T: DeserializeOwned + Serialize>(
    path: impl AsRef<Path>,
    url: impl IntoUrl,
) -> T {
    match File::open(&path) {
        Ok(mut f) => {
            // eprintln!("Loading from {path}.", path = path.as_ref().display());
            let mut buf = String::new();
            f.read_to_string(&mut buf).unwrap();
            serde_json::from_str(&buf).unwrap()
        }
        Err(_) => {
            // eprintln!("Fetching from {0}.", url.as_str());
            let structure = reqwest::get(url)
                .await
                .unwrap()
                .error_for_status()
                .unwrap()
                .json::<T>()
                .await
                .unwrap();
            let f = File::create(&path).unwrap();
            let mut writer = BufWriter::new(f);
            serde_json::to_writer(&mut writer, &structure).unwrap();
            writer.flush().unwrap();
            structure
        }
    }
}

async fn citations_of_part(
    cfr_part: CfrPart,
    part_path: PathBuf,
) -> HashMap<FrCita, HashSet<CfrDivInfo>> {
    // println!("\t[*] Collecting FR citations... ");
    use quick_xml::{
        events::{BytesStart, Event},
        Reader,
    };

    let part_url = format!(
        "https://www.ecfr.gov/api/versioner/v1/full/2024-12-30/title-{0}.xml?part={1}",
        cfr_part.title, cfr_part.part
    );

    let full_xml = match File::open(&part_path) {
        Ok(mut f) => {
            // eprintln!("Loading from {path}.", path = part_path.display());
            let mut buf = String::new();
            f.read_to_string(&mut buf).unwrap();
            buf
        }
        Err(_) => {
            // eprintln!("Fetching from {part_url}.");
            let buf = reqwest::get(part_url)
                .await
                .unwrap()
                .error_for_status()
                .unwrap()
                .text()
                .await
                .unwrap();

            let f = File::create(&part_path).unwrap();
            let mut writer = BufWriter::new(f);
            writer.write_all(buf.as_bytes()).unwrap();
            writer.flush().unwrap();
            buf
        }
    };

    let mut fr_cita_to_cfr_divs: HashMap<FrCita, HashSet<CfrDivInfo>> = HashMap::new();

    let mut reader = Reader::from_str(&full_xml);
    reader.config_mut().trim_text(true);

    static FR_CITA_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[0-9]+ FR [0-9]+").unwrap());
    let mut in_cita_tag = false;
    let mut ancestors = VecDeque::new();
    let mut depth = 0;
    let mut siblings: Vec<VecDeque<BytesStart>> = Vec::new();
    loop {
        match reader.read_event() {
            Err(e) => panic!("Error at position: {0}: {e:?}", reader.error_position()),
            Ok(Event::Eof) => break,
            Ok(Event::Start(e)) => {
                if matches!(e.name().as_ref(), b"CITA") {
                    in_cita_tag = true;
                    // println!("in_cita_tag = {in_cita_tag}");
                } else {
                    in_cita_tag = false;
                }
                // println!(
                //     "{0}{1}",
                //     "\t".repeat(depth),
                //     String::from_utf8_lossy(e.name().as_ref())
                // );
                ancestors.push_front(e.clone());
                if let Some(sibs_at_depth) = siblings.get_mut(depth) {
                    sibs_at_depth.push_back(e);
                } else {
                    siblings.push(VecDeque::new());
                }
                depth += 1;
            }
            Ok(Event::End(e)) => {
                in_cita_tag = false;
                ancestors.pop_front();
                depth -= 1;
                // println!(
                //     "{0}{1}",
                //     "\t".repeat(depth),
                //     String::from_utf8_lossy(e.name().as_ref())
                // );
            }
            Ok(Event::Text(e)) => {
                if in_cita_tag {
                    let this_tag = ancestors.front().unwrap();
                    assert_eq!(this_tag.name().as_ref(), b"CITA");
                    let parent = ancestors.get(1).unwrap();

                    let cita_elem_text = e.unescape().unwrap().to_string();
                    for re_match in FR_CITA_RE.find_iter(&cita_elem_text) {
                        let fr_cita = FrCita::from_str(re_match.as_str()).unwrap();

                        let (div_name, div_ty, div_to_sum);
                        if parent.starts_with(b"DIV") {
                            div_name = parent
                                .try_get_attribute("N")
                                .unwrap()
                                .and_then(|a| Some(String::from_utf8_lossy(&a.value).to_string()))
                                .unwrap();
                            div_ty = parent
                                .try_get_attribute("TYPE")
                                .unwrap()
                                .and_then(|a| Some(String::from_utf8_lossy(&a.value).to_string()))
                                .unwrap();
                            div_to_sum = parent;
                        } else if parent.starts_with(b"EXTRACT") {
                            let grandparent = ancestors.get(2).unwrap();
                            if grandparent.starts_with(b"DIV") {
                                div_name = grandparent
                                    .try_get_attribute("N")
                                    .unwrap()
                                    .and_then(|a| {
                                        Some(String::from_utf8_lossy(&a.value).to_string())
                                    })
                                    .unwrap();
                                div_ty = grandparent
                                    .try_get_attribute("TYPE")
                                    .unwrap()
                                    .and_then(|a| {
                                        Some(String::from_utf8_lossy(&a.value).to_string())
                                    })
                                    .unwrap();
                                div_to_sum = grandparent;
                            } else {
                                // let d = siblings
                                //     .get(depth)
                                //     .unwrap()
                                //     .iter()
                                //     .find_map(
                                //         |e| if e.starts_with(b"HD1") { Some(e) } else { None },
                                //     )
                                //     .unwrap();
                                div_name = format!(
                                    "{0} CFR Part {1} Appendix X",
                                    cfr_part.title, cfr_part.part
                                );
                                div_ty = String::from("EXTRACT");
                                div_to_sum = parent;
                            }
                        } else {
                            unimplemented!(
                                "FR Citation for {0}",
                                String::from_utf8_lossy(parent.name().as_ref())
                            );
                        }

                        let cfr_div_info = CfrDivInfo {
                            name: div_name,
                            ty: div_ty,
                            // TODO: calculate word count and headers
                            word_count: 0,
                        };
                        if let Some(infos) = fr_cita_to_cfr_divs.get_mut(&fr_cita) {
                            infos.insert(cfr_div_info);
                        } else {
                            let mut infos = HashSet::new();
                            infos.insert(cfr_div_info);
                            fr_cita_to_cfr_divs.insert(fr_cita, infos);
                        }
                    }
                }
            }
            _ => {}
        }
    }

    return fr_cita_to_cfr_divs;
}

async fn fr_docs_for_part(
    cfr_part: CfrPart,
    all_agency_abbrvs: Arc<HashMap<String, String>>,
    rule_search_path: PathBuf,
) -> FrDocSearch {
    // Some Parts have letters in them (e.g. 15 CFR 4a) and the FederalRegister.gov API lists documents affecting these parts under just
    // the numerical Part, i.e. 15 CFR 4 for the aforementioned example.
    static RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\D").unwrap());
    let partno = RE.replace_all(&cfr_part.part, "");
    let rule_search_url = format!(
        concat!(
            "https://www.federalregister.gov/api/v1/documents.json",
            "?per_page=1000&order=newest",
            "&conditions[cfr][title]={titleno}",
            "&conditions[cfr][part]={partno}",
            "&conditions[publication_date][gte]=1994-01-01",
            "&conditions[type][]=RULE",
            "&fields[]=abstract",
            "&fields[]=agencies",
            "&fields[]=agency_names",
            "&fields[]=body_html_url",
            "&fields[]=cfr_references",
            "&fields[]=citation",
            "&fields[]=document_number",
            "&fields[]=end_page",
            "&fields[]=publication_date",
            "&fields[]=significant",
            "&fields[]=start_page",
            "&fields[]=title"
        ),
        titleno = cfr_part.title,
        partno = partno,
    );

    let rule_search = match File::open(&rule_search_path) {
        Ok(mut f) => {
            eprintln!("Loading from {path}.", path = rule_search_path.display());
            let mut buf = String::new();
            f.read_to_string(&mut buf).unwrap();
            serde_json::from_str(&buf).unwrap()
        }
        Err(_) => {
            eprintln!("Fetching from {rule_search_url}.");
            let mut rule_search: FrDocSearch = reqwest::get(rule_search_url)
                .await
                .unwrap()
                .error_for_status()
                .unwrap()
                .json()
                .await
                .unwrap();
            // Search results are accrued 1,000 results per page for a maximum of 10 pages
            let mut next_page_url = rule_search.next_page_url.clone();
            while let Some(url) = next_page_url {
                let next_page: FrDocSearch = reqwest::get(url)
                    .await
                    .unwrap()
                    .error_for_status()
                    .unwrap()
                    .json()
                    .await
                    .unwrap();
                next_page_url = next_page.next_page_url.clone();
                rule_search.extend(next_page);
            }

            // Some agency info is essentially malformed data, like the results for 40 CFR Part 799, and doesn't have an agency
            // name. We remove those here so as to not confuse the LLM later.
            // Additionally, the search results don't include the agency short-hand, which is a useful field for the LLM, so we
            // add it here.
            if let Some(results) = rule_search.results.as_mut() {
                for fr_doc in results {
                    let num_agency_names = fr_doc.agency_names.len();
                    let mut valid_agencies = Vec::with_capacity(num_agency_names);
                    let mut agency_abbrvs = Vec::with_capacity(num_agency_names);
                    for name in &fr_doc.agency_names {
                        if let Some(abbrv) = all_agency_abbrvs.get(name) {
                            valid_agencies.push(name.clone());
                            agency_abbrvs.push(abbrv.clone());
                        }
                    }
                    fr_doc.agency_names = valid_agencies;
                    fr_doc.agency_abbrvs = Some(agency_abbrvs);
                }
            }

            let f = File::create(&rule_search_path).unwrap();
            let mut writer = BufWriter::new(f);
            serde_json::to_writer(&mut writer, &rule_search).unwrap();
            writer.flush().unwrap();
            rule_search
        }
    };

    // Check search results make sense. Results are capped at 10 pages of 1,000
    // TODO: fetch the remaining for those above 10,000
    if rule_search.count <= 10000 {
        assert_eq!(rule_search.count, rule_search.result_len() as u32);
    } else {
        assert_eq!(10000, rule_search.result_len());
    }

    return rule_search;
}

async fn make_fr_doc_db(
    fr_docs: &HashMap<FrDocNo, (HashSet<CfrDivInfo>, FrDocInfo)>,
    frdocsdir: &Path,
) -> HashSet<FrDocNo> {
    let rate_limiter = RateLimiter::new(std::time::Duration::from_millis(1));
    let num_rules = fr_docs.len();
    let mut skipped = HashSet::with_capacity(num_rules);
    for (i, (docno, (_, docinfo))) in fr_docs.iter().enumerate() {
        println!(
            "[*] Fetching FR documents... {0}/{num_rules}: {docno}",
            i + 1
        );
        let docdir = frdocsdir.join(format!("{docno}"));
        let docno = docno.clone();
        let docinfo = docinfo.clone();

        let result = rate_limiter
            .throttle(|| async move {
                create_dir_all(&docdir).unwrap();
                if let Ok(mut f) = File::create_new(docdir.join("rule.html")) {
                    let response = match reqwest::get(docinfo.body_html_url.as_ref().unwrap())
                        .await
                        .unwrap()
                        .error_for_status()
                    {
                        Ok(r) => r,
                        Err(e) => {
                            if let Some(reqwest::StatusCode::TOO_MANY_REQUESTS) = e.status() {
                                panic!("Time: {0:?}. {1:}", tokio::time::Instant::now(), docno);
                            }
                            return Some((
                                docno,
                                format!(
                                    "Bad HTML: {0:?}, Err: {e}, Time: {1:?}",
                                    docinfo.body_html_url,
                                    tokio::time::Instant::now()
                                ),
                            ));
                        }
                    };
                    // TODO: assert
                    if !(response.headers().get("Content-Type")
                        == Some(&reqwest::header::HeaderValue::from_bytes(b"text/html").unwrap()))
                    {
                        return Some((docno, "HTML assertion failed".to_string()));
                    }

                    let buf = response.bytes().await.unwrap();
                    f.write_all(&buf).unwrap();
                }

                if let Ok(mut f) = File::create_new(docdir.join("details.toml")) {
                    let details = toml::to_string(&docinfo).unwrap();
                    f.write_all(details.as_bytes()).unwrap();
                }

                None
            })
            .await;
        skipped.insert(result);
    }

    for d_and_e in &skipped {
        if let Some((d, e)) = d_and_e {
            println!("ERR: {e} {d}");
        }
    }
    let skipped: HashSet<FrDocNo> = skipped
        .into_iter()
        .filter_map(|docno_and_err| docno_and_err.map(|v| v.0))
        .collect();

    println!("[*] {0} FR docs skipped", skipped.len());
    skipped
}

async fn cfr_parts_to_fr_docs(cfr_parts: Vec<CfrPart>, datadir: &Path) -> (DataFrame, DataFrame) {
    // This is used to add agency abbreviations to the FR doc info. The field is useful to the LLM but can't be selected in the FederalRegister.gov
    // search API endpoint used in fr_docs_for_part, which gets all the other docinfo.
    let all_agency_info: Vec<FrAllAgencyInfo> = load_or_fetch_json(
        datadir.join("agencies.json"),
        "https://www.federalregister.gov/api/v1/agencies",
    )
    .await;
    let all_agency_abbrvs: HashMap<String, String> = all_agency_info
        .into_iter()
        .filter_map(|agency| {
            agency
                .short_name
                .and_then(|short| Some((agency.name, short)))
        })
        .collect();
    let all_agency_abbrvs = Arc::new(all_agency_abbrvs);

    let cfrdir = datadir.join("cfr-2024-12-30");
    let frdocsdir = datadir.join("fr_docs");

    let mut fr_docs_to_analyze: HashMap<FrDocNo, (HashSet<CfrDivInfo>, FrDocInfo)> = HashMap::new();
    let mut cfr_coverage: HashMap<CfrPart, CfrCovInfo> = HashMap::new();

    for cfr_part in cfr_parts {
        let partdir = cfrdir
            .join(format!("title-{}", cfr_part.title))
            .join(format!("part-{}", cfr_part.part));
        create_dir_all(&partdir).unwrap();

        // Search the eCFR for all the citations of the Federal Register in the given CFR Part
        let fr_citas_to_cfr_divs = tokio::spawn({
            let cfr_part = cfr_part.clone();
            let part_path = partdir.join("part.xml");
            async move { citations_of_part(cfr_part, part_path).await }
        });

        // Search FederalRegister.gov for all documents marked as affecting the given CFR Part
        let fr_docs_affecting = tokio::spawn({
            let cfr_part = cfr_part.clone();
            let all_agency_abbrvs = Arc::clone(&all_agency_abbrvs);
            let rule_search_path = partdir.join("rules.json");
            async move { fr_docs_for_part(cfr_part, all_agency_abbrvs, rule_search_path).await }
        });

        // Join the above tasks
        let (fr_citas_to_cfr_divs, fr_docs_affecting) =
            tokio::join!(fr_citas_to_cfr_divs, fr_docs_affecting);
        let (fr_citas_to_cfr_divs, fr_docs_affecting) =
            (fr_citas_to_cfr_divs.unwrap(), fr_docs_affecting.unwrap());

        // Attempt to match each FR citation to its FR Final Rule document number
        let mut fr_docs_attributed: HashSet<FrDocNo> = HashSet::new();
        let mut fr_citas_unattributed: HashSet<FrCita> = HashSet::new();
        for (fr_cita, cfr_divs) in &fr_citas_to_cfr_divs {
            let mut was_attributed = false;
            for fr_doc in fr_docs_affecting.result_iter() {
                if fr_doc.contains(fr_cita) {
                    // Add this FR document to the list to analyze
                    let docno = &fr_doc.document_number;
                    let (cfr_divs_affected, _) = fr_docs_to_analyze
                        .entry(docno.clone())
                        .or_insert_with(|| (HashSet::new(), fr_doc.clone()));
                    cfr_divs_affected.extend(cfr_divs.iter().map(CfrDivInfo::clone));
                    fr_docs_attributed.insert(docno.clone());
                    was_attributed = true;
                }
            }

            if !was_attributed {
                fr_citas_unattributed.insert(fr_cita.clone());
            }
        }

        cfr_coverage.insert(
            cfr_part,
            CfrCovInfo {
                fr_citas: fr_citas_to_cfr_divs.into_keys().collect(),
                fr_docs_affecting: fr_docs_affecting
                    .result_iter()
                    .map(|r| r.document_number.clone())
                    .collect(),
                fr_docs_attributed,
                fr_citas_unattributed,
            },
        );
    }

    // Fetch the FR docs to analyze
    let fr_docs_skipped = make_fr_doc_db(&fr_docs_to_analyze, &frdocsdir).await;

    // Aggregate the FR doc results into a DataFrame
    let mut fr_docs_iter = fr_docs_to_analyze
        .into_iter()
        .filter(|(docno, _)| fr_docs_skipped.contains(docno));
    let num_rows = fr_docs_iter.by_ref().count();

    let mut fr_docno_col = Vec::with_capacity(num_rows);
    let mut cfr_divs_refd_col = Vec::with_capacity(num_rows);
    let mut fr_doc_cita_col = Vec::with_capacity(num_rows);
    let mut fr_doc_agencies_col = Vec::with_capacity(num_rows);
    let mut fr_doc_agency_abbrvs_col = Vec::with_capacity(num_rows);
    let mut fr_doc_title_col = Vec::with_capacity(num_rows);
    let mut fr_doc_abstract_col = Vec::with_capacity(num_rows);
    let mut fr_doc_pub_date_col = Vec::with_capacity(num_rows);
    let mut fr_doc_cfr_parts_aff_col = Vec::with_capacity(num_rows);
    // As of now, instead of converting FrDocNo, [CfrDivInfo], [String], and [CfrPartAffected]
    // into polars structs, we just serialize them into JSON Strings.
    for (docno, (cfr_divs, docinfo)) in fr_docs_iter {
        fr_docno_col.push(format!("{docno}"));
        cfr_divs_refd_col.push(serde_json::to_string(&cfr_divs).unwrap());
        fr_doc_cita_col.push(docinfo.citation);
        fr_doc_agencies_col.push(serde_json::to_string(&docinfo.agency_names).unwrap());
        fr_doc_agency_abbrvs_col
            .push(serde_json::to_string(&docinfo.agency_abbrvs.unwrap()).unwrap());
        fr_doc_title_col.push(docinfo.title);
        fr_doc_abstract_col.push(docinfo.r#abstract);
        fr_doc_pub_date_col.push(docinfo.publication_date);
        fr_doc_cfr_parts_aff_col.push(serde_json::to_string(&docinfo.cfr_references).unwrap());
    }

    let fr_doc_results = df![
        "fr-docno" => fr_docno_col,
        "cfr-divs-referenced-in" => cfr_divs_refd_col,
        "fr-doc-citation" => fr_doc_cita_col,
        "fr-doc-agencies" => fr_doc_agencies_col,
        "fr-doc-agencies-shorthand" => fr_doc_agency_abbrvs_col,
        "fr-doc-title" => fr_doc_title_col,
        "fr-doc-abstract" => fr_doc_abstract_col,
        "fr-doc-publication-date" => fr_doc_pub_date_col,
        "fr-doc-cfr-parts-affected" => fr_doc_cfr_parts_aff_col
    ]
    .unwrap();

    let num_rows = cfr_coverage.len();
    let mut cfr_title_col = Vec::with_capacity(num_rows);
    let mut cfr_part_col = Vec::with_capacity(num_rows);
    let mut fr_citations_col = Vec::with_capacity(num_rows);
    let mut fr_docs_affecting_col = Vec::with_capacity(num_rows);
    let mut fr_docs_attributed_col = Vec::with_capacity(num_rows);
    let mut fr_citas_unattributed_col = Vec::with_capacity(num_rows);
    let mut fr_docs_unfetched = Vec::with_capacity(num_rows);
    for (cfr_part, cfr_cov) in cfr_coverage {
        cfr_title_col.push(cfr_part.title);
        cfr_part_col.push(cfr_part.part);
        fr_citations_col.push(serde_json::to_string(&cfr_cov.fr_citas).unwrap());
        fr_docs_affecting_col.push(serde_json::to_string(&cfr_cov.fr_docs_affecting).unwrap());
        fr_docs_attributed_col.push(serde_json::to_string(&cfr_cov.fr_docs_attributed).unwrap());
        fr_citas_unattributed_col
            .push(serde_json::to_string(&cfr_cov.fr_citas_unattributed).unwrap());

        let unfetched: HashSet<FrDocNo> = cfr_cov
            .fr_docs_attributed
            .iter()
            .filter(|docno| fr_docs_skipped.contains(docno))
            .map(|docno| docno.clone())
            .collect();
        fr_docs_unfetched.push(serde_json::to_string(&unfetched).unwrap());
    }

    let cfr_cov_results = df![
        "cfr-title" => cfr_title_col,
        "cfr-part" => cfr_part_col,
        "fr-citations" => fr_citations_col,
        "fr-docs-affecting" => fr_docs_affecting_col,
        "fr-docs-attributed" => fr_docs_attributed_col,
        "fr-cita-unattributed" => fr_citas_unattributed_col,
        "fr-docs-unfetched" => fr_docs_unfetched,
    ]
    .unwrap();

    (fr_doc_results, cfr_cov_results)
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize, Serialize)]
struct TitleStructure {
    identifier: Option<String>,
    label: String,
    label_level: String,
    label_description: String,
    reserved: bool,
    r#type: String,
    volumes: Option<Vec<String>>,
    received_on: Option<String>,
    descendant_range: Option<String>,
    children: Option<Vec<TitleStructure>>,
}

async fn extract_part_info(cmd: CliCmd, structuredir: PathBuf) -> Vec<CfrPart> {
    let (titleno, divty, divid) = match &cmd {
        CliCmd::Title { no } => (no, "title", no),
        CliCmd::Part { title, part } => (title, "part", part),
    };
    // if titleno not in CFR_TITLES:
    //     raise ValueError(f"Invalid CFR Title {titleno}")
    if titleno == "35" {
        panic!("Title 35 is fully reserved.");
    }

    let structure: TitleStructure = load_or_fetch_json(
        structuredir.join(format!("title-{titleno}.json")),
        format!("https://www.ecfr.gov/api/versioner/v1/structure/2024-12-30/title-{titleno}.json"),
    )
    .await;

    let mut cfr_parts = Vec::new();
    // Breadth-first search for the speicifed div
    let mut div_queue = VecDeque::new();
    div_queue.push_back(&structure);
    'outer: loop {
        if div_queue.is_empty() {
            panic!("Never found?");
        }
        let div = div_queue.pop_front().unwrap();

        if div.r#type == divty && div.identifier.as_ref().is_some_and(|id| id == divid) {
            // Depth-first search that div and its children for the component CFR parts
            let mut div_stack = VecDeque::new();
            div_stack.push_back(div);
            loop {
                if div_stack.is_empty() {
                    break 'outer;
                }
                let div = div_stack.pop_back().unwrap();

                if div.r#type == "part" && !div.reserved {
                    cfr_parts.push(CfrPart {
                        title: titleno.to_string(),
                        part: div.identifier.as_ref().unwrap().clone(),
                    });
                } else {
                    if let Some(children) = &div.children {
                        for child in children {
                            div_stack.push_back(child);
                        }
                    }
                }
            }
        } else {
            if div.identifier.as_ref().is_none() {
                println!("WEIRD: {div:?}");
            }
            if let Some(children) = &div.children {
                for child in children {
                    div_queue.push_back(child);
                }
            }
        }
    }

    assert!(!cfr_parts.is_empty());
    cfr_parts
}

#[derive(Parser)]
struct Cli {
    /// Directory to store the collected documents and analysis results
    datadir: PathBuf,
    /// A CFR Title to analyze. If a specific Part is not provided, Doge Guard will analyze every Part in the Title.
    #[command(subcommand)]
    cmd: Option<CliCmd>,
}

#[derive(Subcommand)]
enum CliCmd {
    Title { no: String },
    Part { title: String, part: String },
}

#[tokio::main]
async fn main() {
    let subscriber = tracing_subscriber::fmt()
        .with_file(true)
        .with_line_number(true)
        .with_thread_ids(true)
        .finish();
    tracing::subscriber::set_global_default(subscriber).unwrap();

    let cli = Cli::parse();

    if let Some(cmd) = cli.cmd {
        // Fetch and analyze documents for the input CFR Parts
        let structuredir = cli.datadir.join("cfr-2024-12-30").join("structure");
        create_dir_all(&structuredir).unwrap();
        let cfr_parts = extract_part_info(cmd, structuredir).await;
        // println!("CFR Parts: {cfr_parts:?}");
        let (mut fr_doc_data, mut cfr_coverage) =
            cfr_parts_to_fr_docs(cfr_parts, &cli.datadir).await;
        let mut outf = File::create(cli.datadir.join("fr_doc_data.csv")).unwrap();
        CsvWriter::new(&mut outf)
            .include_header(true)
            .with_separator(b',')
            .finish(&mut fr_doc_data)
            .unwrap();

        let mut outf = File::create(cli.datadir.join("cfr_coverage.csv")).unwrap();
        CsvWriter::new(&mut outf)
            .include_header(true)
            .with_separator(b',')
            .finish(&mut cfr_coverage)
            .unwrap();
    }
    println!("Launching front-end (don't hold your breath)...");
}
