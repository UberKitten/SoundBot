export type JSONData =
  | Record<string, unknown>
  | null
  | unknown[]
  | string
  | number;

export function parseInteger(
  maybeInt: string | number | null
): number | undefined {
  if (maybeInt === null) return undefined;
  if (typeof maybeInt === "number")
    return Number.isNaN(maybeInt) ? undefined : Math.floor(maybeInt);

  const parsedInt = parseInt(maybeInt, 10);
  return Number.isNaN(parsedInt) ? undefined : parsedInt;
}

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

export function newElement(
  tag: string,
  innerText?: string,
  options?: { __dangerous_html: boolean }
) {
  const el = document.createElement(tag);
  if (!innerText) return el;

  options?.__dangerous_html
    ? (el.innerHTML = innerText)
    : (el.innerText = innerText);

  return el;
}

export function getElement<T extends HTMLElement>(selector: string): T {
  const el = document.querySelector<T>(selector);
  if (!el) throw new Error("Could not find element");
  return el;
}

export function getInputElement(selector: string) {
  return getElement<HTMLInputElement>(selector);
}

export function getSelectElement(selector: string) {
  return getElement<HTMLSelectElement>(selector);
}

export function getButtonElement(selector: string) {
  return getElement<HTMLButtonElement>(selector);
}

export function getElements<T extends HTMLElement>(
  selector: string,
  minElements = 1
): NodeListOf<T> {
  const el = document.querySelectorAll<T>(selector);
  if (el.length < minElements) throw new Error("Could not find elements");
  return el;
}

export function getInputElements(selector: string) {
  return getElements<HTMLInputElement>(selector);
}

export async function fetchJson(options: {
  url: string;
  method?: string;
  parser?: (json: JSONData) => unknown;
  linkErrorMessage?: string;
  decodeErrorMessage?: string;
  parseErrorMessage?: string;
}) {
  const method = options.method ?? "get";

  const linkErrorMessage =
    options.linkErrorMessage ??
    "Got an error while communicating with the server";

  const decodeErrorMessage =
    options.decodeErrorMessage ??
    "The data received from the server couldn't be decoded as JSON";

  const parseErrorMessage =
    options.parseErrorMessage ??
    "The data received from the server wasn't in the expected format";

  const response = await fetch(options.url);

  if (!response.ok) {
    throw new NetworkError(linkErrorMessage, response);
  }

  // Duplicate so we can keep a usable copy of its ReadableStream
  const dupedRes = response.clone();

  try {
    const json = await response.json();

    if (options.parser) {
      const parsed = options.parser(json);
      if (typeof parsed !== "undefined") return parsed;
    } else {
      return json;
    }
  } catch {
    throw new NetworkError(decodeErrorMessage, dupedRes);
  }

  throw new NetworkError(parseErrorMessage, dupedRes);
}

const errorDisplay = document.querySelector("#app-error") as HTMLElement | null;

export class NetworkError extends Error {
  response: Response;

  constructor(message: string, response: Response) {
    super(message);
    this.name = "NetworkError";
    this.response = response;
  }

  async responseBody() {
    // Clone response to get a second copy of its ReadableStream
    const dupedRes = this.response.clone();

    try {
      const body = await this.response.json();
      return body && typeof body === "object" && body.message
        ? `HTTP ${this.response.status}: ${body.message}`
        : "";
    } catch {
      try {
        const text = await dupedRes.text();
        return text ? `HTTP ${this.response.status}: ${text}` : "";
      } catch {
        return "Response body could not be decoded as text";
      }
    }
  }
}

export function setError(error: unknown) {
  if (!errorDisplay || !(error instanceof Error)) {
    console.error(error);
  } else {
    errorDisplay.innerText = "";
    errorDisplay.append(
      newElement("p", "&#x26A0; \nsomething is borked :c", {
        __dangerous_html: true,
      })
    );

    errorDisplay.append(newElement("p", error.message));

    if (error instanceof NetworkError) {
      error
        .responseBody()
        .then((body) => errorDisplay.append(newElement("p", body)))
        .then(() => errorDisplay.classList.remove("no-display"));
    } else {
      errorDisplay.classList.remove("no-display");
    }
  }
}

export function clearError() {
  if (!errorDisplay) return;

  errorDisplay.innerText = "";
  errorDisplay.classList.add("no-display");
  errorDisplay.classList.remove("delay-2s");
}

export function scheduleBackgroundTask(cb: () => void) {
  if (typeof window.requestIdleCallback !== "undefined") {
    return requestIdleCallback(cb);
  } else {
    return requestAnimationFrame(cb);
  }
}

export function cancelBackgroundTask(id: number) {
  if (typeof window.requestIdleCallback !== "undefined") {
    return cancelIdleCallback(id);
  } else {
    return cancelAnimationFrame(id);
  }
}

export function cancelBackgroundTasks(ids: number[]) {
  if (typeof window.requestIdleCallback !== "undefined") {
    return ids.map((id) => cancelIdleCallback(id));
  } else {
    return ids.map((id) => cancelAnimationFrame(id));
  }
}
