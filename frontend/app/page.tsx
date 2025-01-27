import Link from "next/link";

class FrDocRecord {
  constructor(
    public readonly fr_docno: string,
    public readonly fr_doc_url: string,
    public readonly fr_doc_citation: string,
    public readonly fr_significant: boolean,
    public readonly fr_title: string,
    public readonly cfr_parts: string,
    public readonly cfr_word_count: number,
    public readonly llm_answer: boolean,
  ) { }
}

function formatNumber(num: number) {
  return new Intl.NumberFormat('en-US').format(num);
};

function FrDocRecordView({ record }: { record: FrDocRecord }) {
  return (
    <>
      <td className="border border-slate-700 px-4 py-2">
        <Link href={`/focus/${record.fr_docno}`} className="flex items-center justify-center ">
          <svg className="w-6 h-6 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
          </svg>
        </Link>
      </td>
      <td className="border border-slate-700 px-4 py-2">
        <a href={record.fr_doc_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 flex items-center justify-center group">
          <span className="group-hover:underline">{record.fr_docno}</span>
          <svg className="w-4 h-4 ml-1 group-hover:underline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </td>
      <td className="border border-slate-700 px-4 py-2">
        <div className="flex items-center justify-center">{record.fr_doc_citation}</div></td>
      <td className="border border-slate-700 px-4 py-2">
        <div className="flex items-center justify-center">
          {record.llm_answer ? "✅" : "❌"}
        </div>
      </td>
      <td className="border border-slate-700 px-4 py-2">
        <div className="flex items-center justify-center">
          {record.fr_significant ? "✅" : "❌"}
        </div>
      </td>
      <td className="border border-slate-700 px-4 py-2">
        <div className="flex items-center justify-center">
          {formatNumber(record.cfr_word_count)}
        </div>
      </td>
      <td className="border border-slate-700 px-4 py-2">
        <div className="flex items-center justify-center">
          {record.cfr_parts}
        </div>
      </td>
      <td className="border border-slate-700 px-4 py-2">
        <div className="flex items-center justify-center">
          {record.fr_title}
        </div>
      </td>
    </>
  );
}

function FrDocListView({ data }: { data: FrDocRecord[] }) {
  return (
    <table className="table-auto border border-collapse border-slate-500">
      <thead>
        <tr>
          <th className="border border-slate-600 px-4 py-2">Focus</th>
          <th className="border border-slate-600 px-4 py-2">FR Document Number</th>
          <th className="border border-slate-600 px-4 py-2">FR Citation</th>
          <th className="border border-slate-600 px-4 py-2">Unstatutory</th>
          <th className="border border-slate-600 px-4 py-2">Significant</th>
          <th className="border border-slate-600 px-4 py-2">CFR Words Affected</th>
          <th className="border border-slate-600 px-4 py-2">CFR Parts Affected</th>
          <th className="border border-slate-600 px-4 py-2">Title</th>
        </tr>
      </thead>
      <tbody>
        {data.map(record => (<tr key={record.fr_docno}><FrDocRecordView record={record} /></tr>))}
      </tbody>
    </table>
  )
}

export default function ListPage() {
  const data = [
    new FrDocRecord("05-11384", "https://www.federalregister.gov/documents/2005/06/08/05-11384/updating-generic-pesticide-chemical-tolerance-regulations", "70 FR 33354", true, "Updating Generic Pesticide Chemical Tolerance Regulations", "40 CFR Part 180", 12000, true),
    new FrDocRecord("04-6008", "https://www.federalregister.gov/documents/2005/06/08/05-11384/updating-generic-pesticide-chemical-tolerance-regulations", "69 FR 12542", true, "Pesticide Tolerance Fees; Suspension of Collection", "40 CFR Part 180", 10000, true),
    new FrDocRecord("2013-02392", "https://www.federalregister.gov/documents/2003/05/07/03-11195/pesticide-tolerance-processing-fees-annual-adjustment", "78 FR 8407", false, "Endosulfan; Pesticide Tolerance", "40 CFR Part 180", 11000, true),
  ];

  return (
    <div className="items-center justify-items-center">
      <div className="font-bold justify-self-center my-4">Doge Guard Results</div>
      <FrDocListView data={data} />
    </div>
  );
}
