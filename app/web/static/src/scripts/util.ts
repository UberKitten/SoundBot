export function getDisplayDate(timestamp_ns: number) {
  // convert ns timestamp to ms timestamp then to Date
  const date = new Date(timestamp_ns / 1000 / 1000);

  // format date (undefined means use local system preference)
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function getCanonicalString(str: string): string;
export function getCanonicalString(str: null): undefined;
export function getCanonicalString(str: undefined): undefined;
export function getCanonicalString(str?: string | null): string | undefined;
export function getCanonicalString(str?: string | null): string | undefined {
  // normalize to decompose unicode sequences into compatible strings
  // convert to upper case then lower case to trigger case folding
  // trim whitespace
  return str?.normalize("NFKD").toUpperCase().toLowerCase().trim();
}

export function numericSort(a: number, b: number, order: "asc" | "desc") {
  return order === "asc" ? a - b : b - a;
}

export function alphaSort(rawA: string, rawB: string, order: "asc" | "desc") {
  const a = getCanonicalString(rawA);
  const b = getCanonicalString(rawB);

  return order === "asc" ? a.localeCompare(b) : b.localeCompare(a);
}
