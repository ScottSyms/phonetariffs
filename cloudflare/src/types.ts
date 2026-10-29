export type Row = Record<string, unknown>;

/** Candidate row returned by the FTS/LIKE prefilter, before ranking. */
export type SearchRow = Row & { norm_text: string; row_id: number };

export interface CallParams {
  carrierId: string | null;
  origin: string;
  destination: string;
  serviceType: string;
  onDate: string;
}
