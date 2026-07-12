import type { ReactNode } from "react";

export interface ResponsiveTableRow {
  key: string;
  cells: ReactNode[];
}

/**
 * Yatay kaydırmalı kapsayıcı içinde tablo; erişilebilirlik için `caption`.
 * Dar ekranda tablo `overflow-x-auto` ile kayar (liste sayfası ayrıca kart
 * düzenine geçer, master §10).
 */
export function ResponsiveTable({
  caption,
  head,
  rows,
  emptyLabel,
}: {
  caption: string;
  head: string[];
  rows: ResponsiveTableRow[];
  emptyLabel: string;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-400">{emptyLabel}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-2xl border border-white/10">
      <table className="w-full min-w-[32rem] border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-white/10 bg-white/5 text-left text-xs uppercase tracking-wide text-slate-400">
            {head.map((label) => (
              <th key={label} scope="col" className="px-4 py-3 font-medium">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-white/5 last:border-0">
              {row.cells.map((cell, index) => (
                <td key={index} className="px-4 py-3 align-top text-slate-200">
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
