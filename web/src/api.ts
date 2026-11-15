/** File purpose: Read structured API responses and preserve clear error boundaries. */
export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  /**
   * Inputs: HTTP status and structured server error fields.
   * Outputs: An error carrying the server rejection.
   * Logic: Keep a known rejection distinct from an unknown network outcome.
   * Dependencies: The standard Error class.
   */
  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/**
 * Inputs: A same-origin API path and optional fetch settings.
 * Outputs: The unwrapped success data, or a structured rejection.
 * Logic: Bound requests to ten seconds and accept only explicit success.
 * Dependencies: Browser fetch, AbortController, timers, and the local HTTP API.
 */
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const externalSignal = options.signal;

  /**
   * Inputs: An abort from the caller's effect or operation.
   * Outputs: Cancellation of the linked request.
   * Logic: Preserve caller cancellation without replacing its signal listener.
   * Dependencies: The external signal and this request's AbortController.
   */
  function cancelExternal() { controller.abort(externalSignal?.reason); }

  /**
   * Inputs: Expiry of the ten-second request timer.
   * Outputs: An aborted fetch or unfinished response body.
   * Logic: Leave uncertain save outcomes to the caller's same-request retry flow.
   * Dependencies: AbortController and DOMException.
   */
  function expireRequest() { controller.abort(new DOMException("The request timed out.", "TimeoutError")); }

  if (externalSignal?.aborted) cancelExternal();
  else externalSignal?.addEventListener("abort", cancelExternal, { once: true });
  const timeout = setTimeout(expireRequest, 10_000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: "no-store", credentials: "same-origin" });
    const envelope = await response.json();
    if (!response.ok || envelope.ok !== true) {
      const error = envelope.error ?? {};
      throw new ApiError(response.status, error.code ?? "request_failed", error.message ?? "The request was rejected.", error.details);
    }
    return envelope.data as T;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", cancelExternal);
  }
}

/**
 * Inputs: An unknown request failure.
 * Outputs: A short message suitable for the interface.
 * Logic: Use the server message for known errors and a connection message otherwise.
 * Dependencies: ApiError.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The local service could not be reached. Check the connection and try again.";
}
