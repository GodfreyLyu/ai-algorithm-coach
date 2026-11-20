/** File purpose: Read store-bound API resources with cancellation and lazy refresh. */
import { useEffect, useRef, useState } from "react";
import { ApiError, errorMessage, request } from "./api";

export interface Resource<T> {
  data: T | null;
  dataToken: number | null;
  loading: boolean;
  error: string | null;
  missing: boolean;
}

interface ResourceOptions {
  path: string | null;
  storeId: string | null;
  enabled: boolean;
  refreshToken: number;
  onMismatch: () => void;
}

/**
 * Inputs: A previous resource state.
 * Outputs: The same state without loading.
 * Logic: Stop the loading flag and keep data.
 * Dependencies: None.
 */
function stopLoading<T>(previous: Resource<T>): Resource<T> { return { ...previous, loading: false }; }

/**
 * Inputs: An API path, bound store ID, enabled flag, refresh token, and mismatch callback.
 * Outputs: The latest data, its refresh token, loading state, and any error.
 * Logic: Fetch only while enabled. Skip a fetch when this path and token already loaded.
 *   Clear data when the path changes. Keep old data during a refresh of the same path.
 * Dependencies: React state and effects, request, and AbortController.
 */
export function useStoreResource<T>({ path, storeId, enabled, refreshToken, onMismatch }: ResourceOptions): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ data: null, dataToken: null, loading: false, error: null, missing: false });
  const loadedKey = useRef<string | null>(null);
  const loadedPath = useRef<string | null>(null);
  const mismatch = useRef(onMismatch);
  mismatch.current = onMismatch;

  /**
   * Inputs: The current path, store, enabled flag, and refresh token.
   * Outputs: A started read and its cancellation handler.
   * Logic: Reset data for a new path and ignore results from cancelled reads.
   * Dependencies: request and the store identity header.
   */
  function loadEffect() {
    if (!enabled || !path || !storeId) return;
    const key = `${storeId}:${path}:${refreshToken}`;
    if (loadedKey.current === key) return;
    const samePath = loadedPath.current === path;
    const controller = new AbortController();
    /**
     * Inputs: The previous resource state.
     * Outputs: A loading state.
     * Logic: Keep data only when the same path refreshes.
     * Dependencies: samePath.
     */
    function startLoading(previous: Resource<T>): Resource<T> {
      return {
        data: samePath ? previous.data : null, dataToken: samePath ? previous.dataToken : null,
        loading: true, error: null, missing: false,
      };
    }
    setState(startLoading);
    /**
     * Inputs: None.
     * Outputs: Updated resource state.
     * Logic: Treat 404 as missing data and report store mismatch to the parent.
     * Dependencies: request, ApiError, and errorMessage.
     */
    async function read() {
      try {
        const data = await request<T>(path!, { signal: controller.signal, headers: { "X-Coach-Store-Id": storeId! } });
        if (controller.signal.aborted) return;
        loadedKey.current = key;
        loadedPath.current = path;
        setState({ data, dataToken: refreshToken, loading: false, error: null, missing: false });
      } catch (failure) {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.code === "workspace_mismatch") {
          setState(stopLoading);
          mismatch.current();
        } else if (failure instanceof ApiError && failure.status === 404) {
          loadedKey.current = key;
          loadedPath.current = path;
          setState({ data: null, dataToken: null, loading: false, error: null, missing: true });
        } else {
          const message = errorMessage(failure);
          /**
           * Inputs: The previous resource state.
           * Outputs: The same data with a visible error.
           * Logic: Keep older data visible beside the error.
           * Dependencies: message.
           */
          function showError(previous: Resource<T>): Resource<T> { return { ...previous, loading: false, error: message }; }
          setState(showError);
        }
      }
    }
    void read();
    /**
     * Inputs: Effect cleanup.
     * Outputs: Cancellation of the outstanding read.
     * Logic: Keep slower old responses from replacing newer data.
     * Dependencies: AbortController.
     */
    function cancel() { controller.abort(); }
    return cancel;
  }
  useEffect(loadEffect, [path, storeId, enabled, refreshToken]);

  return state;
}
