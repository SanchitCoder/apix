/** The data-table twin every chart carries — the WCAG-clean equivalent view. */

import type { ReactNode } from "react";

export interface TableSpec {
  caption: string;
  columns: string[];
  rows: ReactNode[][];
}

export function DataTable({ spec }: { spec: TableSpec }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-edge">
      <table className="w-full border-collapse text-sm" style={{ fontVariantNumeric: "tabular-nums" }}>
        <caption className="visually-hidden">{spec.caption}</caption>
        <thead>
          <tr className="border-b border-edge bg-raised text-left">
            {spec.columns.map((column) => (
              <th key={column} scope="col" className="px-3 py-2 font-semibold text-ink-2">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-grid last:border-0 even:bg-stripe">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="px-3 py-2 font-mono text-ink">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
