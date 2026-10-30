// Usage events (what people do in the app, never file contents or addresses). A deployment can
// define window.datumTrack, for example in HEAD_HTML, to forward them to its own analytics.
// Without it, nothing is sent anywhere.

type Params = Record<string, string | number | boolean | undefined>;

declare global {
  interface Window {
    datumTrack?: (event: string, params?: Params) => void;
  }
}

export function track(event: string, params?: Params): void {
  try {
    window.datumTrack?.(event, params);
  } catch {
    // analytics must never break the app
  }
}
