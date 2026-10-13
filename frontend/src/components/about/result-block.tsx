import type { ResultBlock as ResultBlockData } from "@/lib/results";
import { rowBar } from "./bars";
import { ResultBar } from "./result-bar";

export function ResultBlock({ block }: { block: ResultBlockData }) {
  const optimistic = block.datasetTone === "caution";
  const headingId = `result-${block.id}`;
  return (
    <article className="hw-block" aria-labelledby={headingId}>
      <header className="hw-block-head">
        <h3 id={headingId}>{block.title}</h3>
        <p className="hw-block-tag">
          <span className={optimistic ? "tag" : "tag hw-tag-plain"}>{optimistic ? "Development data: optimistic" : "Held-out data"}</span>
        </p>
        <p className="hw-block-dataset">{block.dataset}</p>
      </header>

      <div className="hw-block-body">
        {block.rows.length > 0 ? <p className="hw-key">Bars show the share of cases, from 0% to 100%. A bracket under a bar is the 95% interval.</p> : null}
        {block.rows.length === 0 ? <p className="hw-none">No figures have been measured for this yet.</p> : null}
        {block.rows.length > 0 ? (
          <table className="hw-table">
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col" className="hw-col-value">
                  Result
                </th>
                <th scope="col" className="hw-col-bar">
                  <span>0%</span>
                  <span>100%</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, i) => {
                const bar = rowBar(row);
                return (
                  <tr key={`${i}-${row.metric}`}>
                    <th scope="row" className="hw-metric">
                      <span className="hw-metric-name">{row.metric}</span>
                      {row.note ? <span className="hw-metric-note">{row.note}</span> : null}
                    </th>
                    <td className="hw-value">{row.value}</td>
                    <td className="hw-bar-cell">{bar ? <ResultBar bar={bar} /> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}

        {block.caveats.length > 0 ? (
          <>
            <h4 className="hw-caveats-title">Caveats</h4>
            <ul className="hw-caveats">
              {block.caveats.map((caveat, i) => (
                <li key={`${i}-${caveat}`}>{caveat}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </article>
  );
}
