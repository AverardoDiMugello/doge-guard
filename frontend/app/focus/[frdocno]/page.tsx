class FrDocFullRecord {
    constructor(
        public readonly fr_docno: string,
        public readonly fr_doc_url: string,
        public readonly fr_doc_citation: string,
        public readonly fr_significant: boolean,
        public readonly fr_title: string,
        public readonly cfr_parts: string,
        public readonly cfr_word_count: number,
        public readonly llm_answer: boolean,
        public readonly llm_chunks_used: object[],
    ) { }
}

export default async function FocusPage({
    params,
}: {
    params: Promise<{ frdocno: string }>
}) {
    const frdocno = (await params).frdocno
    const fr_doc = new FrDocFullRecord(
        "05-11384",
        "https://www.federalregister.gov/documents/2005/06/08/05-11384/updating-generic-pesticide-chemical-tolerance-regulations",
        "70 FR 33354",
        true,
        "Updating Generic Pesticide Chemical Tolerance Regulations",
        "40 CFR Part 180",
        12000,
        true,
        [
            {
                "title": "documents/v1/final_rules/04-6008/rule.html",
                "text": "Since the tolerance fee prohibition is statutory, public comment could not change the result dictated by the statute, and is therefore unnecessary and impracticable. In addition, delay in issuing this rule amending the existing regulations could result in confusion on the part of potential petitioners as to what fees are required. Notice and comment would therefore be contrary to the public interest. Accordingly, EPA has concluded that notice and comment on this rule would be impracticable,"
            },
            {
                "title": "documents/v1/final_rules/04-6008/rule.html",
                "text": "1. Docket. EPA has established an official public docket for this action under docket identification (ID) number OPP-2004-0084. The official public docket consists of the documents specifically referenced in this action, any public comments received, and other information related to this action. Although a part of the official docket, the public docket does not include Confidential Business Information (CBI) or other information whose disclosure is restricted by statute. The official public"
            },
            {
                "title": "documents/v1/final_rules/04-6008/rule.html",
                "text": "An electronic version of the public docket is available through EPA's electronic public docket and comment system, EPA Dockets.You may use EPA Dockets at http://www.epa.gov/\\u200bedocket/\\u200b to view public comments, access the index listing of the contents of the official public docket, and to access those documents in the public docket that are available electronically. Although not all docket materials may be available electronically, you may still access any of the publicly available docket"
            },
            {
                "title": "documents/v1/final_rules/04-6008/rule.html",
                "text": "IV. Good Cause Exemption under the APA\\n\\nEPA has determined that notice and comment on this amendment to the tolerance fee regulations is not required. Under the APA (5 U.S.C. 553(b)(3)(B)), a rule is exempt from notice and public comments requirements “when the agency for a good cause finds (and incorporates the finding and a brief statements of reasons therefor in the rule issued) that notice and public procedure thereon are impracticable, unnecessary, or contrary to the public interest.”"
            },
            {
                "title": "documents/v1/final_rules/04-6008/rule.html",
                "text": "1, 2008. EPA is issuing this final rule without notice and opportunity for public comment because there is good cause to do so within the meaning of the Administrative Procedure Act (APA)."
            }
        ]
    );

    return <div>Focusing on {frdocno} ({fr_doc.fr_doc_citation})</div>
}